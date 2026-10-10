#!/usr/bin/env python3
"""Root-only candidate refresh and sanitized evidence for scratch observation.

Only canonical, root-controlled compiler manifests are accepted. Promotion must
stop the refresh timer/service and hold observe.lock while replacing nft rules.
The generated firewall service uses that same lock. This never promotes policy.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time

from egress_policy import PolicyError, compile_policy, unique_fields


def trusted(path: Path) -> None:
    """Reject symlinks and writable/unowned components, including ancestors."""
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PolicyError("untrusted observation path")


def manifest(path: Path) -> dict:
    if os.geteuid() != 0 or not path.is_absolute():
        raise PolicyError("root and canonical manifest required")
    trusted(path)
    data = json.loads(path.read_text(), object_pairs_hook=unique_fields)
    expected = json.loads(compile_policy(data["policy"])["manifest.json"])
    if data != expected or data["policy"]["mode"] != "observe":
        raise PolicyError("generated observe manifest required")
    if path != Path(data["install_directory"]) / "manifest.json":
        raise PolicyError("canonical manifest required")
    return data


@contextmanager
def locked(data: dict):
    path = Path(data["install_directory"]) / "observe.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid or info.st_mode & 0o022:
            raise PolicyError("untrusted observation lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def nft(*args: str, input: str | None = None) -> str:
    return subprocess.run(["/usr/sbin/nft", *args], input=input, text=True,
                          capture_output=True, check=True, timeout=10).stdout


def live(data: dict) -> list:
    rows = json.loads(nft("-j", "list", "table", "inet", data["table"]))["nftables"]
    if not any(row.get("chain", {}).get("name") == data["observe_chain"] for row in rows):
        raise PolicyError("matching live observe table required")
    return rows


def snapshot(data: dict) -> str:
    commands = []
    for i, endpoint in enumerate(data["policy"]["endpoints"]):
        answers = socket.getaddrinfo(endpoint["suffix"], None, type=socket.SOCK_STREAM)
        addresses = {ipaddress.ip_address(answer[4][0]) for answer in answers}
        if not addresses or any(not a.is_global or a.is_multicast for a in addresses):
            raise PolicyError("candidate DNS snapshot incomplete or nonpublic")
        for family in (4, 6):
            target = f"inet {data['table']} e{i}_{family}"
            commands.append(f"flush set {target}")
            selected = sorted(str(a) for a in addresses if a.version == family)
            if selected:
                commands.append(f"add element {target} {{ {', '.join(selected)} }}")
    return "\n".join(commands) + "\n"


def save_state(data: dict, ok: bool) -> None:
    # Private state contains health only, never DNS replies or policy values.
    path = Path(data["install_directory"]) / "observe-state.json"
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump({"refresh_ok": ok, "checked_at": time.time(),
                   "marker": data["observe_marker"]}, output)
    os.replace(temp, path)


def refresh(data: dict) -> None:
    with locked(data):
        live(data)  # Crucially inside the promotion lock, before any write.
        try:
            commands = snapshot(data)
            nft("-f", "-", input=commands)  # One all-or-nothing transaction.
        except (OSError, ValueError, subprocess.SubprocessError):
            save_state(data, False)
            raise
        save_state(data, True)


def report(data: dict) -> dict:
    with locked(data):
        rows = live(data)
        counts = {row["counter"]["name"]: row["counter"]["packets"]
                  for row in rows if "counter" in row}
        total, logged = (counts[k] for k in ("outside_total", "outside_logged"))
        healthy = False
        try:
            path = Path(data["install_directory"]) / "observe-state.json"
            trusted(path)
            state = json.loads(path.read_text())
            age = time.time() - state["checked_at"]
            healthy = (state["refresh_ok"] and 0 <= age <= 90
                       and state["marker"] == data["observe_marker"])
        except (OSError, ValueError, KeyError):
            pass
        return {"candidate_refresh_recent_ok": healthy, "outside_packets": total,
                "logged_packets": logged, "suppressed_packets": total - logged,
                "journal_continuity_and_channel_closure": "OPERATOR_EVIDENCE_REQUIRED"}


def sanitized_event(data: dict, row: dict) -> dict | None:
    message = row.get("MESSAGE", "")
    if not isinstance(message, str) or not message.startswith(data["log_prefix"]):
        return None
    fields = dict(re.findall(r"\b(DST|DPT|PROTO)=([^\s]+)", message))
    if fields.get("PROTO") not in ("TCP", "UDP"):
        return None
    try:
        destination = str(ipaddress.ip_address(fields["DST"]))
        port = int(fields["DPT"])
        stamp = int(row["__REALTIME_TIMESTAMP"])
        if not 1 <= port <= 65535:
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return {"utc_microseconds": stamp, "tenant": data["tenant"],
            "destination": destination, "port": port, "protocol": fields["PROTO"]}


def events(data: dict, since: str) -> None:
    # An explicit UTC boundary, not an arbitrary journalctl argument/expression.
    datetime.datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ")
    # Stream multi-day journals: never buffer every kernel record in memory.
    process = subprocess.Popen(
        ["/usr/bin/journalctl", "-k", "--since", since.replace("T", " ").replace("Z", " UTC"),
         "--no-pager", "-o", "json"], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for line in process.stdout:
            event = sanitized_event(data, json.loads(line))
            if event:
                print(json.dumps(event, sort_keys=True))
        if process.wait() != 0:
            raise PolicyError("journal export incomplete")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def main() -> int:
    try:
        if len(sys.argv) not in (3, 4):
            raise PolicyError("usage")
        action = sys.argv[1]
        data = manifest(Path(sys.argv[2]))
        if action == "refresh" and len(sys.argv) == 3:
            refresh(data)
            print('{"candidate_refresh": "ok"}')
        elif action == "report" and len(sys.argv) == 3:
            print(json.dumps(report(data), sort_keys=True))
        elif action == "events" and len(sys.argv) == 4:
            events(data, sys.argv[3])
        else:
            raise PolicyError("usage")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("[observe] operation refused or failed; observation window requires review", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
