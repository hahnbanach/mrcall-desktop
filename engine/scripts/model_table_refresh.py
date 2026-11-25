#!/usr/bin/env python3
"""Preview a free snapshot refresh; explicitly publish only the reviewed snapshot.

Uses the complete live resolver reader, pure snapshot builder, static gates
and DataBranch writer. No model, ranking, measurement or accounting call.
The caller serializes publishers across checkouts and deploys compatible
consumers before executing. An ambiguous push requires remote reconciliation.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import resolve_models as rm
from model_table_branch import DataBranch

SOURCE = Path(__file__).resolve().parents[2]
REQUIREMENTS = Path("engine/zylch/llm/roles/requirements.json")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_head(repo: DataBranch) -> str:
    if repo._git("status", "--porcelain", "--untracked-files=all").strip():
        raise RuntimeError(f"checkout is not clean: {repo.root}")
    return repo._git("rev-parse", "HEAD").strip()


def canonical_requirements(source: DataBranch, head: str) -> bytes:
    path = source.root / REQUIREMENTS
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("canonical requirements must be a regular committed file")
    committed = subprocess.run(
        ["git", "-C", str(source.root), "cat-file", "blob", f"{head}:{REQUIREMENTS.as_posix()}"],
        capture_output=True, check=False,
    )
    if committed.returncode != 0:
        raise RuntimeError("cannot read canonical requirements from source HEAD: "
                           + committed.stderr.decode("utf-8", errors="replace").strip())
    current = path.read_bytes()
    if current != committed.stdout:
        raise RuntimeError("canonical requirements differ from source HEAD")
    return current


def data_head(data: DataBranch) -> str:
    head = clean_head(data)
    if data._git("branch", "--show-current").strip() != data.branch:
        raise RuntimeError(f"data checkout must be on {data.branch}")
    remote = data._git("ls-remote", "--exit-code", data.remote, f"refs/heads/{data.branch}")
    if remote.split()[0] != head or data._ahead():
        raise RuntimeError("data HEAD differs from the actual remote or tracking branch")
    return head


def manifest(data: DataBranch) -> dict:
    names = data._git("ls-tree", "-r", "--name-only", "-z", "HEAD").split("\0")
    out = {}
    for name in filter(None, names):
        path = data.root / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"data path is not a regular file: {name}")
        out[name] = sha(path.read_bytes())
    return out


def checked_snapshot(req: dict, raw: dict, published: dict) -> dict:
    sources = rm.resolver.read(req, raw)
    snap = rm.snapshot.build(
        sources["catalogue"], sources["endpoints"], rm.candidates.policy(req), sources["read_at"]
    )
    rm.gates.check_snapshot(snap)
    old = json.loads(published["snapshot.json"])
    rm.gates.check_snapshot(old)
    if snap["policy"] != old["policy"]:
        raise RuntimeError("provider policy differs from the published snapshot")
    if published["table.json"] is None:
        raise RuntimeError("published table.json is missing")
    rm.gates.check_table(json.loads(published["table.json"]), req, snap)
    return snap


def raw_hashes(raw: dict) -> dict:
    return {name: sha(raw[name]) for name in ("catalogue", "benchmarks", "endpoints")}


def private_write(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        handle.write(content)


def refresh(data: DataBranch, preview: Path, source: Path,
            approved_receipt_sha256: str | None = None) -> dict:
    preview = preview.resolve()
    if any(preview.is_relative_to(root.resolve()) for root in (source, data.root)):
        raise RuntimeError("preview must be outside both source and data checkouts")
    source_repo = DataBranch(source)
    source_head = clean_head(source_repo)
    req_bytes = canonical_requirements(source_repo, source_head)
    req = rm.resolver.validate_requirements(json.loads(req_bytes))
    with data.lock():
        base = data_head(data)
        before = manifest(data)
        published = data.read()
        if published["snapshot.json"] is None:
            raise RuntimeError("published snapshot.json is missing")
        if approved_receipt_sha256 is None:
            if preview.exists():
                raise RuntimeError("preview directory already exists; choose a new private path")
            raw = rm.read_live(req)
            snap = checked_snapshot(req, raw, published)
            candidate = (rm.gates.dump(snap, 2) + "\n").encode("utf-8")
            diff = "".join(difflib.unified_diff(
                published["snapshot.json"].decode("utf-8").splitlines(keepends=True),
                candidate.decode("utf-8").splitlines(keepends=True),
                fromfile="a/v1/snapshot.json", tofile="b/v1/snapshot.json",
            )).encode("utf-8")
            receipt = {
                "source_head": source_head, "data_head": base,
                "requirements_sha256": sha(req_bytes), "read_at": raw["read_at"],
                "raw_sha256": raw_hashes(raw), "before_sha256": before,
                "snapshot_sha256": sha(candidate), "snapshot_version": snap["version"],
                "diff_sha256": sha(diff), "changed_paths": ["v1/snapshot.json"] if diff else [],
            }
            if (clean_head(source_repo) != source_head or data_head(data) != base
                    or manifest(data) != before or data.read() != published
                    or canonical_requirements(source_repo, source_head) != req_bytes):
                raise RuntimeError("source, requirements or data changed during provider read")
            preview.mkdir(mode=0o700, parents=True)
            rm.save_sources(raw, preview)
            for path in preview.iterdir():
                path.chmod(0o600)
            private_write(preview / "snapshot.json", candidate)
            private_write(preview / "snapshot.diff", diff)
            private_write(preview / "receipt.json", (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
            return receipt
        receipt_bytes = (preview / "receipt.json").read_bytes()
        if sha(receipt_bytes) != approved_receipt_sha256:
            raise RuntimeError("reviewed receipt hash differs")
        receipt = json.loads(receipt_bytes)
        expected = {
            "source_head": source_head, "data_head": base,
            "requirements_sha256": sha(req_bytes), "before_sha256": before,
        }
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise RuntimeError("reviewed source, requirements or data base differs")
        raw = rm.read_sources(preview, req)
        if raw_hashes(raw) != receipt["raw_sha256"] or raw["read_at"] != receipt["read_at"]:
            raise RuntimeError("reviewed provider payloads differ")
        snap = checked_snapshot(req, raw, published)
        candidate = (rm.gates.dump(snap, 2) + "\n").encode("utf-8")
        if (sha(candidate) != receipt["snapshot_sha256"]
                or candidate != (preview / "snapshot.json").read_bytes()
                or snap["version"] != receipt["snapshot_version"]
                or sha((preview / "snapshot.diff").read_bytes()) != receipt["diff_sha256"]):
            raise RuntimeError("reviewed snapshot or diff differs")
        if receipt["changed_paths"] != ["v1/snapshot.json"]:
            raise RuntimeError("reviewed candidate must change only v1/snapshot.json")
        if (clean_head(source_repo) != source_head or data_head(data) != base
                or manifest(data) != before or data.read() != published
                or canonical_requirements(source_repo, source_head) != req_bytes):
            raise RuntimeError("source, requirements or data changed before publication")
        try:
            data.push({"snapshot.json": candidate.decode("utf-8")},
                      f"model-table: free catalog refresh; snapshot {snap['version']}")
        except RuntimeError as err:
            raise RuntimeError(f"{err}; reconcile actual remote state before retrying") from err
        after = manifest(data)
        expected_files = {**before, "v1/snapshot.json": sha(candidate)}
        if after != expected_files or data_head(data) == base:
            raise RuntimeError("publication differs; reconcile actual remote state before retrying")
        if data._git("rev-parse", "HEAD^").strip() != base:
            raise RuntimeError("publication parent differs; reconcile actual remote state")
        changed = data._git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
        if changed != ["v1/snapshot.json"]:
            raise RuntimeError("publication changed other paths; reconcile actual remote state")
        return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-checkout", required=True, type=Path)
    ap.add_argument("--preview", required=True, type=Path)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--approved-receipt-sha256")
    args = ap.parse_args(argv)
    if args.execute != bool(args.approved_receipt_sha256):
        ap.error("--execute and --approved-receipt-sha256 must be supplied together")
    try:
        receipt = refresh(DataBranch(args.data_checkout), args.preview,
                          SOURCE, args.approved_receipt_sha256)
    except (OSError, ValueError, RuntimeError, rm.candidates.Refused, rm.resolver.ConfigError) as err:
        print(f"model_table_refresh: {err}", file=sys.stderr)
        return 1
    action = "Published reviewed snapshot" if args.execute else "Private preview only"
    print(f"{action}: {receipt['snapshot_version']}; receipt {args.preview / 'receipt.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
