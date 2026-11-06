import asyncio
import base64
import json
import sqlite3
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from test_operator_mcp_guarded_main import reply, env, mail, cleanup_test_data, draft_count
from mail_fixture import ROOT
from zylch.services import operator_reply_operations as ops, operator_reply_generation as generation, project_store
from zylch.storage import database as db
from zylch.storage.models import Draft, Email, LlmReservation
from zylch.storage.storage import Storage


def run(value):
    return asyncio.run(value)


def prepare(reply, key='guarded-request-0001', text='Draft using exact evidence'):
    return reply.service.prepare(key, {'source_email_id': reply.context({}, [], reply.actor)['source']['id']}, [], text, reply.actor)


def change_rules(env):
    project_store.write(env.space, 'operator-instructions', 'procedures.md', base64.b64encode(b'New rule').decode(), 1, author='alice')


def test_insert_retry_recovery_single_causal_effect(reply):
    first = run(reply.prepare())
    assert run(reply.prepare()) == first
    assert first['state'] == 'completed'
    assert len(reply.calls) == draft_count() == 1
    assert first['result']['snapshot']['to_addresses'] == ['customer@example.test']
    assert first['current_draft']['matches_original']


def test_changed_same_key_refused(reply):
    run(reply.prepare())
    with pytest.raises(ops.ReplyRefusal, match='payload_conflict'):
        run(prepare(reply, text='Different intentional body'))
    assert len(reply.calls) == 1


def test_concurrent_same_key_one_executor(reply):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def generate(context, request):
            reply.calls.append(request)
            entered.set()
            await release.wait()
            return 'One answer'
        reply.service.generator = generate
        task = asyncio.create_task(reply.prepare())
        await entered.wait()
        pending = await reply.prepare()
        assert pending['state'] == 'running'
        release.set()
        assert (await task)['state'] == 'completed'
    run(scenario())
    assert len(reply.calls) == draft_count() == 1


def test_reuse_existing_row_causally_recorded(reply):
    first = run(reply.prepare())
    second = run(reply.prepare('guarded-request-0002'))
    assert not second['result']['created']
    assert first['result']['draft_id'] == second['result']['draft_id']
    assert draft_count() == 1


def test_historic_snapshot_survives_current_edit(reply):
    result = run(reply.prepare())
    with db.get_engine().begin() as conn:
        conn.execute(update(Draft).values(body='Later edit'))
    recovered = run(reply.service.recover(operation_id=result['operation_id'], actor_binding=reply.actor))
    assert result['result'] == recovered['result']
    assert not recovered['current_draft']['matches_original']


def test_receipt_failure_rolls_back_draft(reply, monkeypatch):
    original = ops.finish_draft_write
    def fail(session, draft):
        original(session, draft)
        raise RuntimeError('failure before transaction commit')
    monkeypatch.setattr(ops, 'finish_draft_write', fail)
    with pytest.raises(RuntimeError, match='failure before transaction commit'):
        run(reply.prepare())
    recovered = run(reply.service.recover(request_key='guarded-request-0001', actor_binding=reply.actor))
    assert recovered['state'] == 'failed_before_dispatch'
    assert draft_count() == 0 and recovered['result'] is None


def test_source_changed_during_generation_refuses_write(reply):
    async def generate(context, request):
        with db.get_engine().begin() as conn:
            conn.execute(update(Email).values(body_plain='Source changed'))
        return 'Answer'
    reply.service.generator = generate
    with pytest.raises(ops.ReplyRefusal, match='context_changed'):
        run(reply.prepare())
    assert draft_count() == 0


def test_revocation_before_write_refuses(reply):
    def revoked(actor):
        raise ops.ReplyRefusal('revoked')
    async def generate(context, request):
        reply.service.revalidate = revoked
        return 'Answer'
    reply.service.generator = generate
    with pytest.raises(ops.ReplyRefusal, match='revoked'):
        run(reply.prepare())
    assert draft_count() == 0


def test_restart_running_becomes_uncertain_no_dispatch(reply):
    run(reply.prepare())
    with db.get_engine().begin() as conn:
        conn.execute(update(ops._operations).values(state='running', executor='previous-process', result=None))
    result = run(reply.service.recover(request_key='guarded-request-0001', actor_binding=reply.actor))
    assert result['state'] == 'uncertain'
    run(reply.prepare())
    assert len(reply.calls) == 1


def test_second_effect_refused_before_write(reply):
    result = run(reply.prepare())
    token = ops._active.set((reply.service, reply.actor, result['operation_id'], [True]))
    try:
        with pytest.raises(ops.ReplyRefusal, match='one_exact_draft'):
            Storage.get_instance().create_draft(reply.actor.mailbox_address, 'other@example.test', 'Other', 'Other')
    finally:
        ops._active.reset(token)
    assert draft_count() == 1


def test_reservation_causal_link_and_second_dispatch_refusal(reply):
    async def generate(context, request):
        with ops._transaction() as conn:
            ops.link_reservation(conn, SimpleNamespace(id='reservation-1', owner_id=reply.actor.profile_uid), {'model': 'native'})
        with ops._transaction() as conn:
            with pytest.raises(ops.ReplyRefusal, match='one_paid_dispatch'):
                ops.link_reservation(conn, SimpleNamespace(id='reservation-2', owner_id=reply.actor.profile_uid), {'model': 'native'})
        return 'Answer'
    reply.service.generator = generate
    assert run(reply.prepare())['reservation_ids'] == ['reservation-1']


def test_reservation_refuses_external_tools(reply):
    async def generate(context, request):
        with ops._transaction() as conn:
            ops.link_reservation(conn, SimpleNamespace(id='r', owner_id=reply.actor.profile_uid), {'tools': [{'name': 'read_memory'}]})
    reply.service.generator = generate
    with pytest.raises(ops.ReplyRefusal, match='no_external_tools'):
        run(reply.prepare())
    assert draft_count() == 0


def test_capability_missing_refuses_before_generation(reply, monkeypatch):
    monkeypatch.setattr(ops, 'capability', lambda: {'available': False})
    with pytest.raises(ops.ReplyRefusal, match='unsupported'):
        run(reply.prepare())
    assert len(reply.calls) == 0


def test_async_reader_and_current_revalidator(reply):
    async def reader(*args):
        await asyncio.sleep(0)
        return reply.context(*args)
    async def validate(actor):
        await asyncio.sleep(0)
        assert actor == reply.actor
    reply.service.context_reader = reader
    reply.service.revalidate = validate
    assert run(reply.prepare())['state'] == 'completed'


def test_actual_budget_reservation_transaction_copies_worker_context(reply, monkeypatch):
    from zylch.llm import budget
    monkeypatch.setattr(budget, 'request_bound', lambda *args: 123)
    monkeypatch.setattr(budget, '_budget', lambda *args: 1000000)
    async def generate(context, request):
        value = await asyncio.to_thread(budget.reserve, {'model': 'native'}, 'direct')
        return 'Answer with reservation ' + value.id
    reply.service.generator = generate
    result = run(reply.prepare())
    with db.get_engine().connect() as conn:
        ids = list(conn.execute(select(LlmReservation.id)).scalars())
    assert result['reservation_ids'] == ids and len(ids) == 1


def test_instruction_revision_changes_immediately_before_persist_roll_back(reply, env, monkeypatch):
    original = generation.persist
    def race(*args):
        change_rules(env)
        return original(*args)
    monkeypatch.setattr(generation, 'persist', race)
    with pytest.raises(ops.ReplyRefusal, match='instructions_changed'):
        run(reply.prepare())
    assert draft_count() == 0
    result = run(reply.service.recover(request_key='guarded-request-0001', actor_binding=reply.actor))
    assert result['state'] == 'failed_before_dispatch' and result['result'] is None


def test_completed_recovery_survives_rule_update_and_source_deletion(reply, env):
    first = run(reply.prepare())
    change_rules(env)
    with db.get_engine().begin() as conn:
        conn.execute(Email.__table__.delete())
    recovered = run(reply.service.recover(operation_id=first['operation_id'], actor_binding=reply.actor))
    assert recovered['result'] == first['result'] and recovered['context_changed']
    assert not recovered['context_status']['source_exists']
    assert recovered['context_status']['instructions_changed'] and len(reply.calls) == 1


def test_service_instance_does_not_change_process_identity(reply):
    result = run(reply.prepare())
    replacement = ops.ReplyOperations(revalidate=lambda actor: None, context_reader=reply.context)
    recovered = run(replacement.recover(operation_id=result['operation_id'], actor_binding=reply.actor))
    assert recovered['state'] == 'completed' and len(reply.calls) == 1


def test_review_outcome_no_draft_and_replay_without_generator(reply):
    async def generate(context, request):
        reply.calls.append(request)
        return ops.ReviewRequired('Commercial conditions not confirmed', ['Price for anonymous cans'])
    reply.service.generator = generate
    result = run(reply.prepare())
    assert result['state'] == 'needs_review'
    assert result['result'] is None and result['current_draft'] is None
    assert result['review']['missing_facts'] == ['Price for anonymous cans']
    assert draft_count() == 0
    reply.service.generator = None
    assert run(reply.prepare()) == result and len(reply.calls) == 1
    replacement = ops.ReplyOperations(revalidate=lambda actor: None, context_reader=reply.context)
    assert run(replacement.recover(operation_id=result['operation_id'], actor_binding=reply.actor))['review'] == result['review']


def test_review_fresh_company_read_and_private_writer_locks(reply, env, monkeypatch):
    original_connect = sqlite3.connect
    reads, locks = [], []
    def connect(database, *args, **kwargs):
        if isinstance(database, str) and database.startswith('file:') and '?mode=ro' in database:
            reads.append(database)
        return original_connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    original_reader = reply.service.locked_instruction_reader
    def reader(session, actor):
        assert 'assignment_profile' not in {row[1] for row in session.connection().exec_driver_sql('PRAGMA database_list')}
        def compete():
            for filename, statement in ((env.memory.url.database, 'UPDATE project_space SET space_id=space_id'), (db.get_engine().url.database, 'UPDATE emails SET body_plain=body_plain')):
                with original_connect(filename, timeout=0.05) as conn:
                    try:
                        conn.execute(statement)
                        conn.commit()
                        locks.append('unexpected commit')
                    except sqlite3.OperationalError as error:
                        locks.append(str(error))
        worker = threading.Thread(target=compete)
        worker.start()
        worker.join(2)
        assert not worker.is_alive()
        return original_reader(session, actor)
    async def generate(context, request):
        return ops.ReviewRequired('Need an approved quote', ['Confirmed price'])
    reply.service.generator = generate
    reply.service.locked_instruction_reader = reader
    result = run(reply.prepare())
    assert result['state'] == 'needs_review' and draft_count() == 0
    assert reads and locks == ['database is locked', 'database is locked']


def test_later_outbound_frozen_and_insert_at_commit_refuses(reply, env, mail, monkeypatch):
    outbound = mail.add('<outbound@example.test>', reply.actor.mailbox_address, 'customer@example.test', folder='"Sent"', reply=ROOT, body='We can investigate 1200 cans', date='Tue, 01 Jan 2030 10:00:00 +0000')
    with db.get_engine().begin() as conn:
        conn.execute(update(Email).where(Email.id == outbound).values(date=datetime(2030, 1, 1, 10)))
    # A human reply is held until its ownership is explicitly acknowledged.
    # Reopen with a later inbound through the actual signed native lifecycle.
    from test_evidence_rpc import assign, result
    _, _, assigned = assign(env)
    intent = result('preview', operation='close', thread_key=ROOT,
                    expected_revision=1, task_id=assigned['task_id'],
                    reason='Handled personally', handled_ref='handled-correspondence-fixture')
    assert result('commit', intent=intent, grant=env.sign(intent))['state'] == 'closed'
    original_root_id = mail.root_id
    mail.root_id = mail.add('<latest-inbound@example.test>', 'customer@example.test', reply.actor.mailbox_address, reply=ROOT, body='Please confirm the current details', date='Wed, 01 Jan 2031 10:00:00 +0000')
    with db.get_engine().begin() as conn:
        conn.execute(update(Email).where(Email.id == mail.root_id).values(date=datetime(2031, 1, 1, 10)))
    assert result('project', thread_key=ROOT)['state'] == 'later-inbound'
    async def generate(context, request):
        assert [row['id'] for row in context['correspondence']['emails']] == [original_root_id, outbound, mail.root_id]
        assert 'body_html' not in context['correspondence']['emails'][0]
        return 'A sourced answer'
    reply.service.generator = generate
    original = ops.finish_draft_write
    def race(session, draft):
        session.execute(Email.__table__.insert().values(id='new-email', owner_id=reply.actor.mailbox_address,
            mailbox_id=reply.actor.mailbox_id, gmail_id='<new-email@example.test>', message_id_header='<new-email@example.test>',
            thread_id=ROOT, in_reply_to=ROOT, references=ROOT, from_email='customer@example.test',
            to_email=reply.actor.mailbox_address, body_plain='Later change', date=datetime.now()))
        return original(session, draft)
    monkeypatch.setattr(ops, 'finish_draft_write', race)
    with pytest.raises(ops.ReplyRefusal, match='correspondence_changed'):
        run(reply.prepare())
    assert draft_count() == 0


def test_correspondence_bounds_duplicates_foreign_and_order(reply):
    from zylch.services.operator_reply_context import snapshot
    row = dict(id='a', mailbox_id=reply.actor.mailbox_id, thread_id=ROOT, body_plain='Hello', date='2030-01-01')
    later = dict(row, id='b', date='2030-01-02')
    assert snapshot([later, row], reply.actor, ROOT) == snapshot([row, later], reply.actor, ROOT)
    for rows in ([row, row], [dict(row, mailbox_id='foreign')], [dict(row, body_plain='x' * 200000)], [dict(row, original_message_id='pec')], [dict(row, id=str(i)) for i in range(101)]):
        with pytest.raises(ops.ReplyRefusal):
            snapshot(rows, reply.actor, ROOT)


def test_structured_generator_outcomes_and_malformed_refusal(monkeypatch):
    class Client:
        async def create_message(self, **kwargs):
            assert 'tools' not in kwargs
            return SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text=json.dumps(value))])
    monkeypatch.setattr('zylch.llm.make_llm_client', lambda: Client())
    value = {'decision': 'draft', 'body': 'A grounded reply'}
    assert run(generation.generate({}, 'draft')) == 'A grounded reply'
    value = {'decision': 'needs_review', 'reason': 'Unknown terms', 'missing_facts': ['Current quote']}
    assert isinstance(run(generation.generate({}, 'draft')), ops.ReviewRequired)
    for value in ({'body': 'old forced draft'}, {'decision': 'draft', 'body': 'Hi', 'extra': True}, {'decision': 'needs_review', 'reason': '', 'missing_facts': []}):
        with pytest.raises(ops.ReplyRefusal):
            run(generation.generate({}, 'draft'))
