"""Manual scratch-fixture probe, not collected by pytest.

Requires the existing inactive scrA2 fixture plus A1/P1 siblings, an empty
host nft ruleset, the installed helper, conntrack and a reviewed nftset-enabled
dnsmasq binary. Explicit --execute-scratch is required. Changes are rolled back.
Never run on the VPS. Take the R_4 scratch lease before invoking.
"""
import hashlib, importlib.util, json, os, pathlib, pwd, re, shutil, subprocess, sys, time
BASE=pathlib.Path(__file__).resolve().parents[2]/'scripts/server'
if len(sys.argv)!=3 or sys.argv[1]!='--execute-scratch' or os.geteuid()!=0:
 raise SystemExit('root only: probe_egress_host.py --execute-scratch ABSOLUTE_DNSMASQ_BINARY')
DNS_BINARY=pathlib.Path(sys.argv[2]).resolve(strict=True)
spec=importlib.util.spec_from_file_location('egress_policy',BASE/'egress_policy.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
uid='scrA2aaaaaaaaaaaaaaaaaaaaaaa2'
user='mc-'+hashlib.sha256(uid.encode()).hexdigest()[:12]
uidn=pwd.getpwnam(user).pw_uid
unit='zylch-server@'+uid+'.service'
def run(*args,check=True,**kw):
 r=subprocess.run(args,check=check,capture_output=True,text=True,**kw)
 return r.stdout.strip()
def show(u,k):return run('systemctl','show',u,'-p',k,'--value')
def emit(s):print(json.dumps({"utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"profile_uid":uid,"unix_uid":uidn,"event":s}),flush=True)
assert show(unit,'ActiveState')=='inactive'
assert show(unit,'User')==user
assert not run('nft','list','tables')
assert not re.search(r'mark=(?!0(?:\s|$))\d+',run('conntrack','-L','-o','extended',check=False))
assert 'MARK' not in run('iptables-save') and 'MARK' not in run('ip6tables-save')
siblings=['zylch-server@scrA1aaaaaaaaaaaaaaaaaaaaaaa1.service','zylch-server@scrP1ppppppppppppppppppppppp1.service']
before={u:[show(u,k) for k in ('MainPID','ActiveState','NRestarts')] for u in siblings}
resolver_before=pathlib.Path('/etc/resolv.conf').read_bytes()
helper_before=hashlib.sha256(pathlib.Path('/usr/local/sbin/mrcall-tenant').read_bytes()).hexdigest()
p={'mode':'enforce','profile_uid':uid,'unix_uid':uidn,'resolver':'127.0.0.54','upstream':'1.1.1.1','endpoints':[{'suffix':'www.googleapis.com','tcp':[443],'udp':[]}]}
files=m.compile_policy(p);manifest=json.loads(files['manifest.json'])
root=pathlib.Path(manifest['install_directory']);table=manifest['table']
services=[n for n in files if n.endswith('.service')]
dnsunit=next(n for n in services if n.startswith('mrcall-dns-'))
fwunit=next(n for n in services if n.startswith('mrcall-egress-'))
dropin=pathlib.Path('/etc/systemd/system')/(unit+'.d')/'50-egress.conf'
binary=pathlib.Path('/usr/local/libexec/mrcall-dnsmasq')
assert not root.exists() and not dropin.exists() and not binary.exists()
assert all(not (pathlib.Path('/etc/systemd/system')/n).exists() for n in services)
installed=[]
try:
 run('systemctl','start',unit)
 assert show(unit,'ActiveState')=='active'
 emit('baseline_daemon_start PASS')
 run('systemctl','stop',unit)
 root.mkdir(parents=True,mode=0o755)
 for n,t in files.items():
  dest=root/n;dest.write_text(t);dest.chmod(0o644)
 binary.parent.mkdir(exist_ok=True)
 shutil.copyfile(DNS_BINARY,binary);binary.chmod(0o755)
 installed.append(binary)
 for n in services:
  dest=pathlib.Path('/etc/systemd/system')/n;dest.write_text(files[n]);installed.append(dest)
 dropin.write_text(files['50-egress.conf']);installed.append(dropin)
 run('nft','-c','-f',str(root/'firewall.nft'))
 run(str(binary),'--test','--conf-file='+str(root/'dnsmasq.conf'))
 run('systemctl','daemon-reload')
 run('systemctl','start',unit)
 assert show(unit,'ActiveState')=='active'
 assert show(dnsunit,'ActiveState')=='active' and show(fwunit,'ActiveState')=='active'
 # systemd before 253 ignores LogFilterPatterns: every lookup would be journaled
 assert show(dnsunit,'LogFilterPatterns').strip(),'LogFilterPatterns not in force (systemd < 253?)'
 pid=show(unit,'MainPID')
 for attempt in range(50):
  content=run('nsenter','-t',pid,'-m','--','cat','/etc/resolv.conf',check=False)
  if content.splitlines() and content.splitlines()[0]=='nameserver 127.0.0.54':break
  time.sleep(0.1)
 else:raise AssertionError('resolver bind not visible after readiness wait')
 emit('daemon_and_dependencies_active_resolver_bound PASS')
 assert 'ready' in run('/usr/local/sbin/mrcall-tenant','create',uid)
 assert show(unit,'MainPID')==pid
 emit('R2_helper_reapply_keeps_filter_and_pid PASS')
 code='''import os,socket,ssl,urllib.request
os.setgroups([]);os.setgid(int(__import__('sys').argv[2]));os.setuid(int(__import__('sys').argv[1]))
assert socket.getaddrinfo('www.googleapis.com',443)
ctx=ssl.create_default_context()
s=ctx.wrap_socket(socket.create_connection(('www.googleapis.com',443),5),server_hostname='www.googleapis.com')
s.sendall(b'GET /robot/v1/metadata/x509/securetoken@system.gserviceaccount.com HTTP/1.1\\r\\nHost: www.googleapis.com\\r\\nConnection: close\\r\\n\\r\\n')
data=s.recv(128)
assert b'200' in data.split(b'\\r\\n')[0]
s.close()
try:socket.create_connection(('1.1.1.1',443),2)
except OSError:pass
else:raise AssertionError('unapproved outbound')
try:socket.getaddrinfo('example.com',443)
except socket.gaierror:pass
else:raise AssertionError('unapproved DNS')
print('tenant_cert_fetch_and_denials PASS')
'''
 emit(run('nsenter','-t',pid,'-m','--','/usr/bin/python3','-c',code,str(uidn),str(pwd.getpwnam(user).pw_gid)))
 assert 'elements' in run('nft','list','table','inet',table)
 emit('observable_tenant_set PASS')
 run('systemctl','restart',unit)
 assert show(unit,'ActiveState')=='active'
 emit('daemon_restart_with_filter PASS')
 # An intentionally failing guard must block the daemon before its exec.
 run('systemctl','stop',fwunit)
 assert show(unit,'ActiveState')=='inactive'
 assert run('nft','list','table','inet',table)
 emit('guard_stop_keeps_rules_and_stops_dependent_daemon PASS')
 run('conntrack','-D','--mark',str(uidn),check=False)
 run('nft','delete','table','inet',table)
 (root/'firewall.nft').write_text('R4 deliberately invalid firewall input\n')
 failed=subprocess.run(['systemctl','start',unit],capture_output=True,text=True)
 assert failed.returncode != 0 and show(unit,'ActiveState')!='active'
 assert show(unit,'MainPID')=='0'
 emit('cold_guard_failure_refuses_daemon_start PASS')
 (root/'firewall.nft').write_text(files['firewall.nft'])
 run('systemctl','reset-failed',unit,dnsunit,fwunit,check=False)
 run('systemctl','start',unit)
 assert show(unit,'ActiveState')=='active'
 emit('cold_guard_recovery PASS')
 run('systemctl','stop',dnsunit)
 assert show(unit,'ActiveState')=='inactive'
 assert run('nft','list','table','inet',table)
 (root/'dnsmasq.conf').write_text('R4-deliberately-invalid-option\n')
 failed=subprocess.run(['systemctl','start',unit],capture_output=True,text=True)
 assert failed.returncode != 0 and show(unit,'MainPID')=='0'
 emit('resolver_failure_keeps_rules_and_refuses_daemon_start PASS')
 (root/'dnsmasq.conf').write_text(files['dnsmasq.conf'])
 run('systemctl','reset-failed',unit,dnsunit,fwunit,check=False)
 run('systemctl','start',unit)
 assert show(unit,'ActiveState')=='active'
 emit('resolver_recovery PASS')
 emit('authentic_IMAP_WhatsApp_LLM_Firebase NOT_RUN_no_credentials')
finally:
 run('systemctl','stop',unit,check=False)
 if dropin.exists():dropin.unlink()
 run('systemctl','stop',dnsunit,check=False)
 run('systemctl','stop',fwunit,check=False)
 run('conntrack','-D','--mark',str(uidn),check=False)
 run('nft','delete','table','inet',table,check=False)
 for dest in installed:
  if dest.exists():dest.unlink()
 if root.exists():shutil.rmtree(root)
 run('systemctl','daemon-reload')
 run('systemctl','reset-failed',unit,dnsunit,fwunit,check=False)
 assert show(unit,'ActiveState')=='inactive'
 assert not run('nft','list','tables')
 assert before=={u:[show(u,k) for k in ('MainPID','ActiveState','NRestarts')] for u in siblings}
 assert pathlib.Path('/etc/resolv.conf').read_bytes()==resolver_before
 assert hashlib.sha256(pathlib.Path('/usr/local/sbin/mrcall-tenant').read_bytes()).hexdigest()==helper_before
 emit('rollback_inactive_baseline_siblings_resolver_helper_unchanged PASS')
