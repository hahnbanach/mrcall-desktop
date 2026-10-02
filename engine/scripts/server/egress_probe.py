#!/usr/bin/env python3
"""Root-only, offline kernel/DNS experiment inside a disposable network namespace.

Usage: sudo python3 egress_probe.py /absolute/path/to/nftset-enabled/dnsmasq
No host firewall, resolver, tenant service or user is modified. Synthetic
servers are confined to the namespace. This does NOT prove live M3 acceptance.
"""
from __future__ import annotations

import atexit
import ctypes
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

from egress_policy import compile_policy


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


def emit(name, value):
    print(json.dumps({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "scope": "isolated-netns", "tenant_uid": 998,
                      "probe": name, "result": value}), flush=True)


ANSWERS = {1: "9.9.9.11", 28: "2606:4700::11"}


def dns_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("8.8.8.8", 53))
    while True:
        data, peer = server.recvfrom(4096)
        end = 12
        while data[end]:
            end += data[end] + 1
        end += 1
        qtype = struct.unpack("!H", data[end:end + 2])[0]
        question = data[12:end + 4]
        is_alias = data[12:end].startswith(b"\x05alias")
        address = ("9.9.9.13" if qtype == 1 else "2606:4700::13") if is_alias else ANSWERS[1 if qtype == 1 else 28]
        payload = socket.inet_pton(socket.AF_INET if qtype == 1 else socket.AF_INET6, address)
        if qtype not in (1, 28):
            answer = b""
            count = 0
        else:
            answer = b"\xc0\x0c" + struct.pack("!HHIH", qtype, 1, 60, len(payload)) + payload
            count = 1
            if is_alias:
                cname = b"\x04edge\x07allowed\x07example\x00"
                alias = b"\xc0\x0c" + struct.pack("!HHIH", 5, 1, 60, len(cname)) + cname
                answer = alias + cname + struct.pack("!HHIH", qtype, 1, 60, len(payload)) + payload
                count = 2
        packet = data[:2] + struct.pack("!HHHHH", 0x8180, 1, count, 0, 0) + question + answer
        server.sendto(packet, peer)


def echo_server(address):
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    server = socket.socket(family, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((address, 443))
    server.listen()
    def echo(conn):
        with conn:
            while True:
                data = conn.recv(512)
                if not data:
                    break
                conn.sendall(data)
    while True:
        conn, _ = server.accept()
        threading.Thread(target=echo, args=(conn,), daemon=True).start()


def udp_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("9.9.9.11", 444))
    while True:
        data, peer = server.recvfrom(512)
        server.sendto(data, peer)


CLIENT = '''import os,socket,sys
os.setgroups([]);os.setgid(998);os.setuid(int(sys.argv[1]))
s=socket.socket(socket.AF_INET6 if ':' in sys.argv[2] else socket.AF_INET,socket.SOCK_STREAM)
s.settimeout(1)
try:
 s.connect((sys.argv[2],int(sys.argv[3])))
 print('CONNECTED',flush=True)
 for line in sys.stdin:
  s.sendall(b'probe'); print('ECHO' if s.recv(5)==b'probe' else 'CLOSED',flush=True)
except OSError:
 print('DENIED',flush=True)
'''


def client(address, uid=998, port=443):
    return subprocess.Popen([sys.executable, "-c", CLIENT, str(uid), address, str(port)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)


def query(name, qtype="A", resolver="127.0.0.54", uid=998):
    return run("setpriv", f"--reuid={uid}", "--regid=998", "--clear-groups", "dig",
               f"@{resolver}", name, qtype, "+time=1", "+tries=1", "+short").strip()


def cleanup(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def interrupted(signum, frame):
    raise SystemExit(128 + signum)


def main():
    if os.geteuid() != 0 or len(sys.argv) not in (2, 3):
        raise SystemExit("run as root with dnsmasq binary path [--full-timeout]")
    if len(sys.argv) == 3 and sys.argv[2] != "--full-timeout":
        raise SystemExit("unknown probe option")
    expiry_seconds = 300 if len(sys.argv) == 3 else 3
    binary = str(Path(sys.argv[1]).resolve(strict=True))
    version = run(binary, "--version")
    if "no-nftset" in version or " nftset " not in version:
        raise SystemExit("dnsmasq must be built with nftset")
    # Namespace isolation is established before any ip/nft command. Threads
    # and all child processes created afterward inherit it. No named netns
    # mount or persistent host artifact is needed.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.unshare(0x40000000) != 0:  # CLONE_NEWNET
        raise SystemExit("cannot create disposable network namespace")
    run("ip", "link", "set", "lo", "up")
    for address in ("8.8.8.8/32", "9.9.9.11/32", "9.9.9.12/32", "9.9.9.13/32", "9.9.9.99/32", "169.254.169.254/32", "2606:4700::11/128", "2606:4700::99/128"):
        run("ip", "address", "add", address, "dev", "lo", "nodad")
    threading.Thread(target=dns_server, daemon=True).start()
    threading.Thread(target=udp_server, daemon=True).start()
    for address in ("9.9.9.11", "9.9.9.12", "9.9.9.13", "9.9.9.99", "169.254.169.254", "127.0.0.1", "2606:4700::11", "2606:4700::99"):
        threading.Thread(target=echo_server, args=(address,), daemon=True).start()
    time.sleep(0.1)
    p = {"profile_uid": "scratchR4A", "unix_uid": 998, "resolver": "127.0.0.54",
         "upstream": "8.8.8.8", "endpoints": [{"suffix": "allowed.example", "tcp": [443], "udp": [444]},
                       {"suffix": "other.example", "tcp": [445], "udp": []}]}
    artifacts = compile_policy(p)
    processes = []
    atexit.register(cleanup, processes)
    signal.signal(signal.SIGTERM, interrupted)
    with tempfile.TemporaryDirectory(prefix="r4-netns-") as directory:
        root = Path(directory)
        nft = root / "rules.nft"
        # Accelerated timeout has identical rules/admission logic. The full
        # five-minute live-channel gate remains separate and unproved.
        nft.write_text(artifacts["firewall.nft"].replace("timeout 5m;", f"timeout {expiry_seconds}s;"))
        conf = root / "dnsmasq.conf"
        conf.write_text(artifacts["dnsmasq.conf"])
        preopened = client("9.9.9.99")
        processes.append(preopened)
        assert preopened.stdout.readline().strip() == "CONNECTED"
        run("nft", "-c", "-f", str(nft))
        run("nft", "-f", str(nft))
        emit("atomic_nft_load", "PASS")
        logfile = (root / "dnsmasq.log").open("w+")
        resolver = subprocess.Popen([binary, "--keep-in-foreground", f"--conf-file={conf}", "--pid-file="], stdout=logfile, stderr=logfile)
        processes.append(resolver)
        try:
            time.sleep(0.2)
            assert resolver.poll() is None
            answer = query("allowed.example")
            if answer != "9.9.9.11":
                logfile.flush(); logfile.seek(0)
                emit("dns_diagnostic", logfile.read())
                emit("answer_diagnostic", answer)
            assert answer == "9.9.9.11"
            assert query("allowed.example", "AAAA") == "2606:4700::11"
            emit("dns_populates_A_AAAA", "PASS")
            own_table = json.loads(artifacts["manifest.json"])["table"]
            assert "9.9.9.13" not in run("nft", "list", "set", "inet", own_table, "e0_4")
            blocked_alias = client("9.9.9.13")
            processes.append(blocked_alias)
            assert blocked_alias.stdout.readline().strip() == "DENIED"
            assert query("alias.allowed.example").splitlines()[-1] == "9.9.9.13"
            assert "9.9.9.13" in run("nft", "list", "set", "inet", own_table, "e0_4")
            assert "9.9.9.13" not in run("nft", "list", "set", "inet", own_table, "e1_4")
            admitted_alias = client("9.9.9.13")
            processes.append(admitted_alias)
            assert admitted_alias.stdout.readline().strip() == "CONNECTED"
            emit("CNAME_unique_address_intended_set_only", "PASS")
            udp_code = """import os,socket
os.setgroups([]);os.setgid(998);os.setuid(998)
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(1)
s.connect(('9.9.9.11',444));s.send(b'probe');assert s.recv(5)==b'probe'
"""
            run(sys.executable, "-c", udp_code)
            emit("approved_UDP_port", "PASS")
            assert query("unrelated.example") == ""
            emit("unapproved_DNS", "PASS")
            for address in ("9.9.9.11", "2606:4700::11"):
                proc = client(address)
                processes.append(proc)
                assert proc.stdout.readline().strip() == "CONNECTED"
                emit("allow_" + address, "PASS")
            for address in ("9.9.9.99", "2606:4700::99", "169.254.169.254", "127.0.0.1"):
                proc = client(address)
                processes.append(proc)
                assert proc.stdout.readline().strip() == "DENIED"
                emit("deny_" + address, "PASS")
            preopened.stdin.write("probe\n"); preopened.stdin.flush()
            assert preopened.stdout.readline().strip() == "DENIED"
            emit("preopened_forbidden_flow", "PASS")
            proc = client("9.9.9.11")
            processes.append(proc)
            assert proc.stdout.readline().strip() == "CONNECTED"
            proc.stdin.write("probe\n"); proc.stdin.flush()
            assert proc.stdout.readline().strip() == "ECHO"
            emit("expiry_wait_seconds", expiry_seconds)
            time.sleep(expiry_seconds + 0.2)
            proc.stdin.write("probe\n"); proc.stdin.flush()
            result = proc.stdout.readline().strip()
            assert result == "ECHO"
            fresh = client("9.9.9.11")
            processes.append(fresh)
            assert fresh.stdout.readline().strip() == "DENIED"
            emit("new_flow_after_expiry", "DENIED")
            emit("open_connection_after_element_expiry", result)
            assert query("allowed.example") == "9.9.9.11"
            again = client("9.9.9.11")
            processes.append(again)
            assert again.stdout.readline().strip() == "CONNECTED"
            emit("resolve_and_reconnect_after_expiry", "PASS")
            ANSWERS[1] = "9.9.9.12"
            assert query("allowed.example") == "9.9.9.12"
            rotated = client("9.9.9.12")
            processes.append(rotated)
            assert rotated.stdout.readline().strip() == "CONNECTED"
            ANSWERS[1] = "9.9.9.11"
            emit("changed_DNS_answer_admitted", "PASS")
            # A distinct second tenant must remain independent across A's
            # reload and rollback, including a previously admitted socket.
            sibling = dict(p, profile_uid="scratchR4B", unix_uid=999, resolver="127.0.0.55")
            sibling_files = compile_policy(sibling)
            sibling_nft = root / "sibling.nft"
            sibling_nft.write_text(sibling_files["firewall.nft"])
            sibling_conf = root / "sibling.conf"
            sibling_conf.write_text(sibling_files["dnsmasq.conf"])
            run("nft", "-f", str(sibling_nft))
            sibling_resolver = subprocess.Popen([binary, "--keep-in-foreground", f"--conf-file={sibling_conf}", "--pid-file="], stdout=logfile, stderr=logfile)
            processes.append(sibling_resolver)
            time.sleep(0.2)
            assert query("allowed.example", resolver="127.0.0.55", uid=999) == "9.9.9.11"
            sibling_client = client("9.9.9.11", uid=999)
            processes.append(sibling_client)
            assert sibling_client.stdout.readline().strip() == "CONNECTED"
            for resolver_address in ("8.8.8.8", "127.0.0.55"):
                try:
                    query("allowed.example", resolver=resolver_address)
                except subprocess.CalledProcessError:
                    emit("deny_dns_" + resolver_address, "PASS")
                else:
                    raise AssertionError("DNS escape")
            # Rules reset while dnsmasq remains alive: cache disabled must
            # repopulate the empty set on the next query.
            run("nft", "-f", str(nft))
            assert query("allowed.example") == "9.9.9.11"
            emit("cold_table_reload", "PASS")
            sibling_table = json.loads(sibling_files["manifest.json"])["table"]
            sibling_state = run("nft", "-s", "list", "table", "inet", sibling_table)
            own_table = json.loads(artifacts["manifest.json"])["table"]
            run("nft", "delete", "table", "inet", own_table)
            assert run("nft", "-s", "list", "table", "inet", sibling_table) == sibling_state
            sibling_client.stdin.write("probe\n"); sibling_client.stdin.flush()
            assert sibling_client.stdout.readline().strip() == "ECHO"
            restored = client("9.9.9.99")
            processes.append(restored)
            assert restored.stdout.readline().strip() == "CONNECTED"
            emit("tenant_rollback_sibling_preserved", "PASS")
            emit("live_application_gate", "NOT_RUN")
            return 3 if result != "ECHO" else 0
        finally:
            cleanup(processes)
            logfile.close()


if __name__ == "__main__":
    raise SystemExit(main())
