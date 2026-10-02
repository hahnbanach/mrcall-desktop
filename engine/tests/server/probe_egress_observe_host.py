"""Explicit scratch-only observe -> enforce -> rollback, never run on the VPS.

Requires the R4 published lease, inactive scrA2 fixture, active A1/P1 siblings,
an empty host ruleset, and the previously reviewed nftset-enabled dnsmasq build.
Only synthetic payloads/public certificate retrieval; no credentials are read.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import threading
import time

BASE = Path(__file__).resolve().parents[2] / 'scripts/server'
sys.path.insert(0, str(BASE))
from egress_policy import compile_policy
import egress_observe as observer


def run(*args, check=True, **kwargs):
    return subprocess.run(args, check=check, capture_output=True, text=True, **kwargs).stdout.strip()


def show(unit, prop):
    return run('systemctl', 'show', unit, '-p', prop, '--value')


def emit(event):
    print(json.dumps({'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                      'profile_uid': UID, 'unix_uid': ACCOUNT.pw_uid, 'event': event}), flush=True)


def listener(address, udp=False):
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    server = socket.socket(family, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
    server.bind((address, 0))
    if not udp:
        server.listen()
    servers.append(server)
    def serve():
        try:
            while True:
                if udp:
                    data, peer = server.recvfrom(1024)
                    server.sendto(data, peer)
                else:
                    conn, _ = server.accept()
                    with conn:
                        data = conn.recv(1024)
                        if data:
                            conn.sendall(data)
        except OSError:
            pass
    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1]


CLIENT = '''import os,socket,ssl,sys
os.setgroups([]);os.setgid(int(sys.argv[2]));os.setuid(int(sys.argv[1]))
'''


def client(code, namespace=True):
    args = ['nsenter', '-t', show(UNIT, 'MainPID'), '-m', '--'] if namespace else []
    return run(*args, '/usr/bin/python3', '-c', CLIENT + code,
               str(ACCOUNT.pw_uid), str(ACCOUNT.pw_gid), timeout=30)


def echo_code(address, port, udp=False, denied=False, count=1):
    return f'''
s=socket.socket({socket.AF_INET6 if ':' in address else socket.AF_INET}, {socket.SOCK_DGRAM if udp else socket.SOCK_STREAM})
s.settimeout(2)
try:
 s.connect(({address!r},{port}))
 for _ in range({count}):
  s.send(b'R4_SYNTHETIC_PAYLOAD_CANARY')
  assert s.recv(1024)==b'R4_SYNTHETIC_PAYLOAD_CANARY'
except OSError:
 assert {denied!r}
else:
 assert not {denied!r}
s.close()
'''


KNOWN = '''
assert socket.getaddrinfo('www.googleapis.com',443)
s=ssl.create_default_context().wrap_socket(socket.create_connection(('www.googleapis.com',443),5),server_hostname='www.googleapis.com')
s.sendall(b'GET /robot/v1/metadata/x509/securetoken@system.gserviceaccount.com HTTP/1.1\\r\\nHost: www.googleapis.com\\r\\nConnection: close\\r\\n\\r\\n')
assert b'200' in s.recv(128).split(b'\\r\\n')[0]
s.close()
'''

if len(sys.argv) != 3 or sys.argv[1] != '--execute-scratch' or os.geteuid() != 0:
    raise SystemExit('root: probe_egress_observe_host.py --execute-scratch ABS_DNSMASQ_BINARY')
DNS_SOURCE = Path(sys.argv[2]).resolve(strict=True)
UID = 'scrA2aaaaaaaaaaaaaaaaaaaaaaa2'
TAG = hashlib.sha256(UID.encode()).hexdigest()[:12]
ACCOUNT = pwd.getpwnam('mc-' + TAG)
UNIT = f'zylch-server@{UID}.service'
assert show(UNIT, 'ActiveState') == 'inactive' and show(UNIT, 'User') == ACCOUNT.pw_name
assert not run('nft', 'list', 'tables')
siblings = ['zylch-server@scrA1aaaaaaaaaaaaaaaaaaaaaaa1.service',
            'zylch-server@scrP1ppppppppppppppppppppppp1.service']
before = {u: [show(u, k) for k in ('MainPID', 'ActiveState', 'NRestarts')] for u in siblings}
assert all(v[1] == 'active' for v in before.values())
resolver_before = Path('/etc/resolv.conf').read_bytes()
helper_before = hashlib.sha256(Path('/usr/local/sbin/mrcall-tenant').read_bytes()).hexdigest()
p = {'mode': 'observe', 'profile_uid': UID, 'unix_uid': ACCOUNT.pw_uid,
     'resolver': '127.0.0.54', 'upstream': '1.1.1.1',
     'endpoints': [{'suffix': 'www.googleapis.com', 'tcp': [443], 'udp': []}]}
files = compile_policy(p)
data = json.loads(files['manifest.json'])
root = Path(data['install_directory'])
table = data['table']
obsunit = f'mrcall-observe-{TAG}.service'
refreshunit = f'mrcall-observe-refresh-{TAG}.service'
timer = refreshunit.replace('.service', '.timer')
enforced = compile_policy(dict(p, mode='enforce'))
enforce_units = [n for n in enforced if n.endswith('.service')]
systemd = Path('/etc/systemd/system')
units = [n for n in files if n.endswith(('.service', '.timer'))] + enforce_units
dropin = systemd / (UNIT + '.d') / '50-egress.conf'
binary = Path('/usr/local/libexec/mrcall-dnsmasq')
helpers = Path('/usr/local/libexec/mrcall-egress')
assert not any(x.exists() for x in (root, dropin, binary, helpers))
assert not any((systemd / n).exists() for n in units)
private = '10.254.254.4'
assert private not in run('ip', '-j', 'address', 'show')
servers, installed = [], []
since = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
canary_table = 'mc_r4_sibling_canary'
try:
    run('systemctl', 'start', UNIT)
    pid = show(UNIT, 'MainPID')
    for _ in range(50):
        daemon_resolver = run('nsenter', '-t', pid, '-m', '--', 'cat', '/etc/resolv.conf', check=False)
        if daemon_resolver:
            break
        time.sleep(.1)
    else:
        raise AssertionError('daemon namespace readiness')
    run('nft', '-f', '-', input=f'table inet {canary_table} {{\n chain output {{\n type filter hook output priority 11; policy accept;\n }}\n}}\n')
    sibling_rules = run('nft', '-s', 'list', 'table', 'inet', canary_table)
    run('ip', 'address', 'add', private + '/32', 'dev', 'lo')
    targets = [(a, listener(a, udp), udp) for a in ('127.0.0.1', private, '::1') for udp in (False, True)]
    for a, port, udp in targets:
        client(echo_code(a, port, udp))
    root.mkdir(parents=True, mode=0o755)
    helpers.mkdir(parents=True, mode=0o755)
    for name in ('egress_policy.py', 'egress_observe.py'):
        shutil.copyfile(BASE / name, helpers / name)
    for name, content in files.items():
        (root / name).write_text(content)
        if name in units:
            (systemd / name).write_text(content)
            installed.append(systemd / name)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'start', obsunit, timer)
    run('systemctl', 'start', refreshunit)
    trusted = observer.manifest(root / 'manifest.json')
    assert observer.report(trusted)['candidate_refresh_recent_ok']
    assert show(UNIT, 'MainPID') == pid
    assert run('nsenter', '-t', pid, '-m', '--', 'cat', '/etc/resolv.conf') == daemon_resolver
    emit('observe_attached_without_daemon_or_resolver_change PASS')
    for a, port, udp in targets:
        client(echo_code(a, port, udp))
    client('''
# External UDP and TCP DNS remain usable, without printing queries/replies.
query=b'\\x52\\x34\\x01\\x00\\x00\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x03www\\x0agoogleapis\\x03com\\x00\\x00\\x01\\x00\\x01'
for kind in (socket.SOCK_DGRAM,socket.SOCK_STREAM):
 s=socket.socket(socket.AF_INET,kind);s.settimeout(5);s.connect(('1.1.1.1',53))
 s.send((len(query).to_bytes(2,'big') if kind==socket.SOCK_STREAM else b'')+query)
 assert s.recv(4096);s.close()
''')
    emit('observe_unknown_TCP_UDP_loopback_private_IPv6_external_DNS_usable PASS')
    # Freeze the periodic snapshot for deterministic known-set classification.
    run('systemctl', 'stop', timer, refreshunit)
    time.sleep(1)
    # Resolve before counters: the original daemon DNS is intentionally outside.
    address = run('/usr/bin/python3', '-c', "import socket;print(socket.gethostbyname('www.googleapis.com'))")
    run('nft', '-f', '-', input=f'add element inet {table} e0_4 {{ {address} }}\n')
    initial = observer.report(trusted)['outside_packets']
    client(KNOWN.replace("assert socket.getaddrinfo('www.googleapis.com',443)", '').replace("(('www.googleapis.com',443),5)", f"(({address!r},443),5)"))
    assert observer.report(trusted)['outside_packets'] == initial
    emit('observe_known_set_is_not_logged_as_outside PASS')
    a, port, udp = targets[1]
    client(echo_code(a, port, udp, count=200))
    report = observer.report(trusted)
    assert report['suppressed_packets'] > 0 and report['logged_packets'] > 0
    emit('observe_burst_suppression_visible PASS')
    time.sleep(1)
    raw = run('journalctl', '-k', '--since', since.replace('T', ' ').replace('Z', ' UTC'), '-o', 'json', '--no-pager')
    rows = [json.loads(line) for line in raw.splitlines() if line]
    relevant = [r for r in rows if isinstance(r.get('MESSAGE'), str) and r['MESSAGE'].startswith(data['log_prefix'])]
    assert relevant and all('R4_SYNTHETIC_PAYLOAD_CANARY' not in r['MESSAGE'] for r in relevant)
    events = [observer.sanitized_event(data, r) for r in relevant]
    assert any(e and e['port'] == port and e['protocol'] == 'UDP' for e in events)
    exported = run('/usr/bin/python3', str(helpers / 'egress_observe.py'), 'events', str(root / 'manifest.json'), since)
    assert exported and all(set(json.loads(line)) == {'utc_microseconds','tenant','destination','port','protocol'} for line in exported.splitlines())
    emit('actual_kernel_events_payload_absent_sanitized_export PASS')
    # Broken manifest makes the updater fail but cannot influence the daemon.
    (root / 'manifest.json').write_text('{}')
    failure = subprocess.run(['systemctl', 'start', refreshunit], capture_output=True)
    assert failure.returncode and show(UNIT, 'MainPID') == pid
    client(echo_code(a, port, udp))
    (root / 'manifest.json').write_text(files['manifest.json'])
    run('systemctl', 'reset-failed', refreshunit)
    run('systemctl', 'stop', timer, refreshunit, obsunit)
    # Failed observer start likewise has no dependency on the live daemon.
    (root / 'firewall.nft').write_text('invalid scratch observation rules\n')
    failure = subprocess.run(['systemctl', 'start', obsunit], capture_output=True)
    assert failure.returncode and show(UNIT, 'MainPID') == pid
    client(echo_code(a, port, udp))
    emit('refresh_and_observer_failure_leave_daemon_and_traffic_running PASS')
    run('systemctl', 'stop', UNIT)
    run('conntrack', '-D', '--mark', str(ACCOUNT.pw_uid), check=False)
    # Queue a real refresh behind the same lock used by the generated loader.
    # It must inspect the new mode only after promotion releases the lock.
    pending = None
    try:
        with observer.locked(data):
            pending = subprocess.Popen(['/usr/bin/python3', str(helpers / 'egress_observe.py'),
                                        'refresh', str(root / 'manifest.json')],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(100):
                if pending.poll() is not None:
                    raise AssertionError('refresh did not wait for promotion lock')
                if 'lock' in Path(f'/proc/{pending.pid}/wchan').read_text():
                    break
                time.sleep(.02)
            else:
                raise AssertionError('refresh did not reach policy lock')
            run('nft', '-f', '-', input=enforced['firewall.nft'])
            promoted = run('nft', '-s', 'list', 'table', 'inet', table)
        pending.communicate(timeout=10)
        assert pending.returncode == 2
        assert run('nft', '-s', 'list', 'table', 'inet', table) == promoted
        emit('queued_refresh_serialized_and_refused_after_locked_promotion PASS')
    finally:
        if pending is not None and pending.poll() is None:
            pending.kill()
            pending.communicate()
    # Preserve observe manifest for an actual stale updater test after promotion.
    for name, content in enforced.items():
        if name != 'manifest.json':
            (root / name).write_text(content)
        if name in enforce_units:
            (systemd / name).write_text(content)
            installed.append(systemd / name)
    shutil.copyfile(DNS_SOURCE, binary)
    binary.chmod(0o755)
    dropin.write_text(enforced['50-egress.conf'])
    installed.append(dropin)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'start', UNIT)
    for _ in range(50):
        if run('nsenter', '-t', show(UNIT, 'MainPID'), '-m', '--', 'cat', '/etc/resolv.conf', check=False).startswith('nameserver 127.0.0.54'):
            break
        time.sleep(.1)
    else:
        raise AssertionError('enforced resolver readiness')
    rules_before = run('nft', '-s', 'list', 'table', 'inet', table)
    stale = subprocess.run(['/usr/bin/python3', str(helpers / 'egress_observe.py'), 'refresh', str(root / 'manifest.json')], capture_output=True)
    assert stale.returncode == 2
    assert run('nft', '-s', 'list', 'table', 'inet', table) == rules_before
    emit('stale_observe_updater_refused_after_enforcement PASS')
    client(KNOWN)
    for a, port, udp in targets:
        client(echo_code(a, port, udp, denied=True))
    client('''
try: socket.create_connection(('1.1.1.1',53),2)
except OSError: pass
else: raise AssertionError('external DNS bypass')
''')
    emit('enforce_known_usable_unknown_TCP_UDP_IPv6_and_external_DNS_denied PASS')
    run('systemctl', 'stop', UNIT)
    dropin.unlink()
    run('systemctl', 'stop', *enforce_units)
    run('conntrack', '-D', '--mark', str(ACCOUNT.pw_uid), check=False)
    with observer.locked(data):
        run('nft', 'delete', 'table', 'inet', table)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'start', UNIT)
    for a, port, udp in targets:
        client(echo_code(a, port, udp))
    assert run('nsenter', '-t', show(UNIT, 'MainPID'), '-m', '--', 'cat', '/etc/resolv.conf') == daemon_resolver
    assert run('nft', '-s', 'list', 'table', 'inet', canary_table) == sibling_rules
    emit('rollback_restores_unknowns_and_resolver_sibling_rules_unchanged PASS')
    emit('authentic_channels_and_72h_VPS_window NOT_RUN')
finally:
    run('systemctl', 'stop', UNIT, check=False)
    for name in units:
        run('systemctl', 'stop', name, check=False)
    for dest in installed:
        dest.unlink(missing_ok=True)
    run('conntrack', '-D', '--mark', str(ACCOUNT.pw_uid), check=False)
    for name in (table, canary_table):
        run('nft', 'delete', 'table', 'inet', name, check=False)
    for server in servers:
        server.close()
    run('ip', 'address', 'del', private + '/32', 'dev', 'lo', check=False)
    if root.exists():
        shutil.rmtree(root)
    if helpers.exists():
        shutil.rmtree(helpers)
    binary.unlink(missing_ok=True)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'reset-failed', UNIT, *units, check=False)
    assert show(UNIT, 'ActiveState') == 'inactive'
    assert not run('nft', 'list', 'tables')
    assert before == {u: [show(u, k) for k in ('MainPID', 'ActiveState', 'NRestarts')] for u in siblings}
    assert Path('/etc/resolv.conf').read_bytes() == resolver_before
    assert hashlib.sha256(Path('/usr/local/sbin/mrcall-tenant').read_bytes()).hexdigest() == helper_before
    emit('cleanup_original_state_sibling_PIDs_host_resolver_helper_preserved PASS')
