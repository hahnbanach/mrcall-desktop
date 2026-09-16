"""Bounded live comparison of frozen private engine requests.

API key is read from stdin only. This is an explicit paid evaluation command,
not a production worker. A reviewed manifest supplies exact cases and cells.
The output directory and ledger require a private evaluation marker. No retries;
a persisted dispatch intent prevents replay after an interrupted invocation.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_manifest(path):
    manifest = json.loads(path.read_text())
    cases = {c['id']: c for c in manifest['cases']}
    if len(cases) != len(manifest['cases']):
        raise ValueError('Duplicate case IDs')
    cells = manifest['cells']
    if len({c['id'] for c in cells}) != len(cells):
        raise ValueError('Duplicate cell IDs')
    for cell in cells:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', cell['id']):
            raise ValueError('Cell IDs must be filename-safe')
        if cell['case_id'] not in cases:
            raise ValueError('Unknown case')
        if 'model' in cases[cell['case_id']]['request']:
            raise ValueError('Model must come from the cell, not the case')
    return manifest, cases, cells


def existing_intents(path):
    if not path.exists():
        return set()
    # A partial/corrupt record fails closed; never guess whether dispatch happened.
    return {r['cell_id'] for r in map(json.loads, path.read_text().splitlines())
            if r['event'] == 'intent'}


def validate_scratch(root):
    if root.is_symlink() or any((root / name).is_symlink() for name in ('ledger.db', 'evaluation-ledger.json', '.env')) or root.stat().st_mode & 0o077:
        raise ValueError('Evaluation ledger directory must be private')
    marker = json.loads((root / 'evaluation-ledger.json').read_text())
    if marker.get('purpose') != 'isolated-model-evaluation':
        raise ValueError('Not an evaluation ledger')
    with sqlite3.connect(f'file:{root / "ledger.db"}?mode=ro', uri=True) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        earliest = db.execute('SELECT MIN(ts) FROM llm_usage').fetchone()[0] if 'llm_usage' in tables else None
    if earliest and datetime.fromisoformat(marker['accounting_time']).date() > datetime.fromisoformat(earliest).date():
        raise ValueError('Accounting day would omit previous settled usage')
    allowed = {'llm_usage', 'llm_reservations', 'llm_billing_authorizations'}
    if tables != allowed:
        raise ValueError('Ledger contains unexpected tables; refusing production storage')
    return marker


def reasoning_support(manifest, marker):
    """Enable reviewed reasoning only inside this isolated evaluation process."""
    config = manifest.get('reasoning_experiment')
    if config is None:
        return None
    expected = {'version': 1, 'model': 'moonshotai/kimi-k3',
                'provider': 'digitalocean', 'effort': 'max',
                'allowed_caps': [2048, 4096, 8192]}
    if config.get('version') == 2:
        expected.update(version=2, wire_protocol='chat-completions-v1')
    if config != expected or marker.get('reasoning_experiment') != expected:
        raise ValueError('Reasoning experiment lacks exact ledger authorization')
    if any(c['model'] != expected['model'] for c in manifest['cells']):
        raise ValueError('Reasoning experiment supports K3 only')
    route = manifest.get('routing', {}).get(expected['model'], {})
    if route.get('only') != [expected['provider']]:
        raise ValueError('Reasoning comparison requires the frozen provider')
    path = Path(__file__).with_name('evaluation_reasoning_transport.py')
    spec = importlib.util.spec_from_file_location('evaluation_reasoning_transport', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    with ExitStack() as cleanup:
        run(cleanup)


def write_wire(path, body):
    path.write_text(json.dumps(body, ensure_ascii=False))


def run(cleanup):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-active', type=int, default=4, choices=range(1, 13))
    parser.add_argument('--per-model', type=int, default=2, choices=range(1, 5))
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    marker = validate_scratch(args.ledger)
    root = args.ledger.resolve()
    manifest, cases, cells = load_manifest(args.manifest)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.output.stat().st_mode & 0o077:
        raise ValueError('Output must be private')
    lock = (root / 'evaluation.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    owner = marker['owner']
    os.environ.update(ZYLCH_PROFILE_DIR=str(root), ZYLCH_DB_PATH=str(root / 'ledger.db'),
                      OWNER_ID=owner, EMAIL_ADDRESS='evaluation@example.test')
    from zylch.storage import database
    if str(database.get_engine().url.database) != str(root / 'ledger.db'):
        raise ValueError('Wrong database binding')
    import zylch.llm.client as llm
    from zylch.llm import budget
    reasoning = reasoning_support(manifest, marker)
    if reasoning is not None:
        cleanup.enter_context(reasoning.pricing_override(
            reviewed_experiment=True,
            protocol=manifest['reasoning_experiment'].get('wire_protocol', 'messages-v1')))
    from zylch.llm.openrouter_pricing import RATES, request_bound
    from zylch.llm.usage import call_site
    # Fixed accounting day retains prior experiment liabilities across midnight.
    accounting_time = datetime.fromisoformat(marker['accounting_time'])
    budget._now = lambda: accounting_time
    request_clock = ContextVar('evaluation_request_clock', default=manifest['as_of'])
    llm.current_datetime_line = lambda: request_clock.get()
    routing = manifest.get('routing', {})
    for model, override in routing.items():
        if override != marker.get('reviewed_routing', {}).get(model):
            raise ValueError('Routing override has no reviewed ledger authorization')
        rates = tuple(Decimal(override[k]) for k in ('input_rate', 'output_rate'))
        if model not in RATES or any(not rate.is_finite() or rate <= 0 for rate in rates):
            raise ValueError('Invalid reviewed rates')
        if not override.get('only') or not all(isinstance(x, str) for x in override['only']):
            raise ValueError('Reviewed provider pin required')
        RATES[model] = rates
    initial = budget.budget_snapshot(owner)
    if initial['budget_usd'] != marker['cap_usd'] or initial['budget_usd'] > 20:
        raise ValueError('Saved cap and reviewed marker disagree')
    bounds = {}
    for cell in cells:
        request = {'temperature': 1.0, 'service_tier': 'standard_only',
                   **cases[cell['case_id']]['request'], 'model': cell['model']}
        clock_token = request_clock.set(cases[cell['case_id']].get('datetime_line', manifest['as_of']))
        try:
            request['system'] = llm._with_datetime(request.get('system'))
            bounds[cell['id']] = request_bound(request)
        finally:
            request_clock.reset(clock_token)
    fingerprint = digest(manifest)
    header_path = args.output / 'manifest.json'
    if header_path.exists() and digest(json.loads(header_path.read_text())) != fingerprint:
        raise ValueError('Cannot resume output with a different manifest')
    preflight = {'cells': len(cells), 'models': dict(Counter(c['model'] for c in cells)),
                 'sum_reservation_bounds_usd': sum(bounds.values()) / 1e6,
                 'max_request_bound_usd': max(bounds.values(), default=0) / 1e6,
                 'initial_budget': initial, 'manifest_sha256': fingerprint}
    print(json.dumps(preflight), flush=True)
    if not args.execute:
        return
    key = sys.stdin.read().strip()
    if not key:
        raise ValueError('Key required on stdin')
    if not header_path.exists():
        header_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    journal_path = args.output / 'attempts.jsonl'
    attempted = existing_intents(journal_path)
    # Reconstruct availability failures on resume; no reset through restarting.
    streaks = Counter()
    if journal_path.exists():
        for r in map(json.loads, journal_path.read_text().splitlines()):
            if r['event'] == 'result' and r.get('http', {}).get('dispatched'):
                group = (r['model'], r['stage'])
                streaks[group] = 0 if r.get('availability_ok', r.get('status') == 'returned' and r.get('response', {}).get('stop_reason') in ('end_turn', 'tool_use')) else streaks[group] + 1
    journal_lock = threading.Lock()
    def append(row):
        with journal_lock, journal_path.open('a') as out:
            out.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            out.flush()
            os.fsync(out.fileno())
    import httpx
    def dispatch(cell):
        case = cases[cell['case_id']]
        response_meta = {'dispatched': False}
        def observe_request(request):
            response_meta['dispatched'] = True
        def observe(response):
            response.read()
            response_meta['status_code'] = response.status_code
            response_meta['request_id'] = response.headers.get('x-request-id')
            response_meta['retry_after'] = response.headers.get('retry-after')
            # Store response body privately for diagnosis; never request headers/key.
            (args.output / (cell['id'] + '.http.json')).write_text(response.text)
        clock_token = request_clock.set(case.get('datetime_line', manifest['as_of']))
        started = time.monotonic()
        row = {'event': 'result', 'cell_id': cell['id'], 'case_id': cell['case_id'],
               'model': cell['model'], 'stage': case['stage']}
        try:
            client = llm.LLMClient('openrouter', api_key=key, model=cell['model'])
            if reasoning is not None:
                cls = (reasoning.ChatReasoningEvaluationClient
                       if manifest['reasoning_experiment'].get('wire_protocol') == 'chat-completions-v1'
                       else reasoning.ReasoningEvaluationClient)
                client._client = cls(key)
            with httpx.Client(timeout=600 if reasoning is not None else 180, follow_redirects=False,
                              event_hooks={'request': [observe_request], 'response': [observe]}) as http:
                class RoutedHTTP:
                    def post(self, url, *, json, headers):
                        override = routing.get(cell['model'])
                        if override:
                            json['provider']['only'] = override['only']
                        response_meta['wire_sha256'] = digest(json)
                        if reasoning is not None:
                            response_meta['reasoning_controls'] = {k: json.get(k) for k in ('thinking', 'output_config', 'reasoning', 'max_tokens')}
                            write_wire(args.output / (cell['id'] + '.request.json'), json)
                        response_meta['provider_policy'] = json['provider']
                        return http.post(url, json=json, headers={**headers, 'X-OpenRouter-Metadata': 'enabled'})
                client._client._http = RoutedHTTP()
                with call_site('evaluation.controlled.' + cell['id']):
                    response = client.create_message_sync(**case['request'])
            row.update(status='returned', response=json.loads(json.dumps(response._raw, default=vars)))
            expected_stop = 'tool_use' if case['stage'] == 'task.detect' else 'end_turn'
            row['completion_ok'] = (row['response'].get('stop_reason') == expected_stop
                                    and not row['response'].get('validation_error'))
            # Completed text in place of a mandatory tool is a contract failure,
            # not an outage. Preserve it for grading; do not retry it.
            row['availability_ok'] = row['response'].get('stop_reason') in ('end_turn', 'tool_use')
        # Dispatch boundary journals all provider failures without retrying them.
        except Exception as exc:  # noqa: BLE001
            row.update(status='unavailable', exception=type(exc).__name__, detail=str(exc))
        request_clock.reset(clock_token)
        row.update(seconds=round(time.monotonic() - started, 2), http=response_meta)
        append(row)
        return row
    pending = [c for c in cells if c['id'] not in attempted]
    active = {}
    model_active = Counter()
    # Existing engine reservations are atomic, including concurrent calls.
    with ThreadPoolExecutor(max_workers=max(1, len({c['model'] for c in cells})) * args.per_model) as pool:
        while pending or active:
            for cell in list(pending):
                group = (cell['model'], cases[cell['case_id']]['stage'])
                if streaks[group] >= 3:
                    pending.remove(cell)
                    append({'event': 'not_dispatched', 'cell_id': cell['id'], 'reason': 'availability_circuit'})
                    continue
                if len(active) >= args.max_active or model_active[cell['model']] >= args.per_model:
                    continue
                snapshot = budget.budget_snapshot(owner)
                if snapshot['pricing_fault'] or snapshot['remaining_usd'] * 1e6 < bounds[cell['id']]:
                    # In-flight settlement may return allowance. Wait before final skip.
                    if active:
                        continue
                    pending.remove(cell)
                    append({'event': 'not_dispatched', 'cell_id': cell['id'], 'reason': 'budget'})
                    continue
                append({'event': 'intent', 'cell_id': cell['id'], 'request_sha256': digest(cases[cell['case_id']]['request']),
                        'bound_micro_usd': bounds[cell['id']], 'at': datetime.utcnow().isoformat()})  # noqa: DTZ003 -- preserve existing naive-UTC journal format
                pending.remove(cell)
                future = pool.submit(dispatch, cell)
                active[future] = cell
                model_active[cell['model']] += 1
            if not active:
                break
            done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                cell = active.pop(future)
                row = future.result()
                model_active[cell['model']] -= 1
                group = (row['model'], row['stage'])
                if row['http']['dispatched']:
                    streaks[group] = 0 if row.get('availability_ok', False) else streaks[group] + 1
                snapshot = budget.budget_snapshot(owner)
                print(json.dumps({k: row[k] for k in ('cell_id','model','stage','status','seconds')} |
                                 {'spent': snapshot['spent_usd'], 'held': snapshot['reserved_usd']}), flush=True)
    final = budget.budget_snapshot(owner)
    (args.output / 'budget.json').write_text(json.dumps(final, indent=2))
    print(json.dumps({'complete': True, 'budget': final}), flush=True)


if __name__ == '__main__':
    main()
