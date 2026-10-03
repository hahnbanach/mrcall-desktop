#!/usr/bin/env python3
"""Compile operator-reviewed egress policy; never install or enable it.

Scratch experiment for sandbox M3. Output is NOT production-approved. No
profile, credentials, voice configuration, DNS or host state is read. Run:
    python3 egress_policy.py policy.json NEW_OUTPUT_DIRECTORY
Review the generated files before installing anything. The R_4 plan defines
host locking, identity checks, installation, evidence gates and rollback.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path


class PolicyError(ValueError):
    """Invalid policy; diagnostics deliberately omit supplied values."""


def fields(value: object, expected: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise PolicyError("unexpected or missing policy fields")
    return value


def integer(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise PolicyError("integer outside allowed range")
    return value


def host(value: object) -> str:
    if not isinstance(value, str) or len(value) > 253:
        raise PolicyError("invalid DNS suffix")
    if value != value.lower() or len(value.split('.')) < 2:
        raise PolicyError("DNS suffix must be lowercase and qualified")
    labels = value.split('.')
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels):
        raise PolicyError("invalid DNS suffix")
    if not re.fullmatch(r"[a-z]{2,63}", labels[-1]):
        raise PolicyError("invalid DNS suffix ending")
    # Avoid well-known multi-label public suffixes. This is not a PSL: root
    # must review ownership of every suffix, including less common registries.
    if value in {"co.uk", "org.uk", "com.au", "co.jp", "com.br", "co.nz"}:
        raise PolicyError("public suffix cannot be approved")
    return value


def validate(raw: object) -> dict:
    p = fields(raw, {"mode", "profile_uid", "unix_uid", "resolver", "upstream", "endpoints"})
    if p["mode"] not in ("observe", "enforce"):
        raise PolicyError("explicit observe or enforce mode required")
    uid = p["profile_uid"]
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9]{1,128}", uid):
        raise PolicyError("invalid profile uid")
    unix_uid = integer(p["unix_uid"], 1, 2147483647)
    # One upstream (the original string form, kept so existing policy digests
    # do not change) or a list of up to four, which dnsmasq fails over between.
    single = isinstance(p["upstream"], str)
    upstreams = [p["upstream"]] if single else p["upstream"]
    if not isinstance(upstreams, list) or not 1 <= len(upstreams) <= 4:
        raise PolicyError("expected one through four upstream resolvers")
    if any(not isinstance(x, str) or not re.fullmatch(r"[0-9A-Fa-f:.]+", x)
           for x in [p["resolver"], *upstreams]):
        raise PolicyError("resolver addresses must be unscoped IP literals")
    try:
        resolver = ipaddress.IPv4Address(p["resolver"])
        parsed = [ipaddress.ip_address(x) for x in upstreams]
    except (ValueError, TypeError):
        raise PolicyError("invalid resolver address") from None
    if resolver not in ipaddress.ip_network("127.0.0.0/24") or int(resolver) & 255 not in range(2, 255):
        raise PolicyError("dedicated resolver must be 127.0.0.2 through 127.0.0.254")
    if any(not x.is_global or x.is_multicast for x in parsed):
        raise PolicyError("upstream resolver must be a public unicast address")
    if len(set(parsed)) != len(parsed):
        raise PolicyError("duplicate upstream resolver")
    upstream = str(parsed[0]) if single else [str(x) for x in parsed]
    endpoints = p["endpoints"]
    if not isinstance(endpoints, list) or not 1 <= len(endpoints) <= 64:
        raise PolicyError("expected 1 through 64 endpoint policies")
    clean = []
    seen = set()
    for entry in endpoints:
        entry = fields(entry, {"suffix", "tcp", "udp"})
        suffix = host(entry["suffix"])
        # dnsmasq's longest-suffix matching must not silently shadow another
        # policy or leave a broader set attached to the wrong port group.
        if any(suffix == x or suffix.endswith('.' + x) or x.endswith('.' + suffix) for x in seen):
            raise PolicyError("overlapping DNS suffixes")
        seen.add(suffix)
        rule = {"suffix": suffix}
        for proto in ("tcp", "udp"):
            values = entry[proto]
            if not isinstance(values, list) or len(values) > 16:
                raise PolicyError("invalid port list")
            ports = [integer(v, 1, 65535) for v in values]
            if len(set(ports)) != len(ports) or 53 in ports or 853 in ports:
                raise PolicyError("duplicate or external DNS port")
            rule[proto] = sorted(ports)
        if not rule["tcp"] and not rule["udp"]:
            raise PolicyError("endpoint has no permitted ports")
        clean.append(rule)
    return dict(mode=p["mode"], profile_uid=uid, unix_uid=unix_uid, resolver=str(resolver),
                upstream=upstream, endpoints=sorted(clean, key=lambda x: x["suffix"]))


def upstream_list(p: dict) -> list[str]:
    return [p["upstream"]] if isinstance(p["upstream"], str) else list(p["upstream"])


def compile_policy(raw: object) -> dict[str, str]:
    p = validate(raw)
    if p["mode"] == "observe":
        return compile_observe(p)
    tag = hashlib.sha256(p["profile_uid"].encode()).hexdigest()[:12]
    name = f"mc-{tag}"
    table = f"mc_egress_{tag}"
    root = f"/etc/mrcalld/egress/{name}"
    firewall = f"mrcall-egress-{tag}.service"
    dnsunit = f"mrcall-dns-{tag}.service"
    unit = f"zylch-server@{p['profile_uid']}.service"
    # add/delete/recreate occur in one nft transaction, never a global flush.
    nft = [f"add table inet {table}", f"delete table inet {table}", f"table inet {table} {{",
           ' comment "mrcall mode=enforce"']
    # log-queries: a name outside the policy is refused here (local=/#/), not
    # by the firewall, so only this log shows it ("config <name> is NXDOMAIN";
    # egress_refused.py lists them). Names and addresses only, no payloads.
    dns = ["# Generated scratch policy; no global resolver changes.",
           "no-resolv", "no-hosts", "bind-interfaces", f"listen-address={p['resolver']}",
           "port=53", "user=nobody", "group=nogroup", "cache-size=0",
           "max-ttl=0", "local=/#/", "stop-dns-rebind", "domain-needed", "log-facility=-",
           "log-queries"]
    for i, entry in enumerate(p["endpoints"]):
        for family in (4, 6):
            nft.append(f" set e{i}_{family} {{ type ipv{family}_addr; flags timeout; timeout 5m; size 4096; }}")
        dns.extend(f"server=/{entry['suffix']}/{up}" for up in upstream_list(p))
        dns.append(f"nftset=/{entry['suffix']}/4#inet#{table}#e{i}_4,6#inet#{table}#e{i}_6")
    # Every reject is preceded by its own rate-limited log rule. The log rule
    # never accepts: past its limit it just does not match, and the reject
    # after it still applies. Kernel log prefix: "mc-deny-<tag> ".
    log = f'limit rate 10/second burst 20 packets log prefix "mc-deny-{tag} " level info'
    private4 = ("{ 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, "
                "172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 }")
    private6 = "{ ::/96, ::ffff:0:0/96, 64:ff9b::/96, 64:ff9b:1::/48, 100::/64, fc00::/7, fe80::/10, ff00::/8 }"
    nft.extend([" chain output {", "  type filter hook output priority 10; policy accept;",
                f"  meta skuid {p['unix_uid']} jump tenant", " }", " chain tenant {",
                "  ct direction reply ct state established counter accept",
                f"  ip daddr {p['resolver']} udp dport 53 counter accept",
                f"  ip daddr {p['resolver']} tcp dport 53 counter accept",
                f"  ip daddr {private4} {log}",
                f"  ip daddr {private4} counter reject",
                f"  ip6 daddr {private6} {log}",
                f"  ip6 daddr {private6} counter reject"])
    nft.append(f"  ct state established ct mark {p['unix_uid']} counter accept")
    for i, entry in enumerate(p["endpoints"]):
        for family, selector in ((4, "ip"), (6, "ip6")):
            for proto in ("tcp", "udp"):
                if entry[proto]:
                    ports = ", ".join(map(str, entry[proto]))
                    nft.append(f"  {selector} daddr @e{i}_{family} {proto} dport {{ {ports} }} ct mark set {p['unix_uid']} counter accept")
    nft.extend([f"  {log}", "  counter reject with icmpx type admin-prohibited", " }", "}"])
    firewall_text = f"""[Unit]
Description=MrCall tenant egress firewall {name}
Before={dnsunit} {unit}
After=nftables.service

[Service]
Type=oneshot
ExecStart=/usr/bin/flock -x {root}/observe.lock /usr/sbin/nft -f {root}/firewall.nft
RemainAfterExit=yes
# Deliberately no ExecStop: stopping a dependency must never open egress.
"""
    dns_text = f"""[Unit]
Description=MrCall tenant DNS {name}
Requires={firewall}
After={firewall} network.target
Before={unit}

[Service]
Type=forking
RuntimeDirectory=mrcall-dns-{tag}
PIDFile=/run/mrcall-dns-{tag}/dnsmasq.pid
ExecStart=/usr/local/libexec/mrcall-dnsmasq --conf-file={root}/dnsmasq.conf --pid-file=/run/mrcall-dns-{tag}/dnsmasq.pid
Restart=on-failure
RestartSec=1
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_CHOWN
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
"""
    dropin = f"""[Unit]
Requires={firewall} {dnsunit}
After={firewall} {dnsunit}

[Service]
BindReadOnlyPaths={root}/resolv.conf:/etc/resolv.conf
"""
    manifest = {"status": "scratch-experiment-not-production-approved", "tenant": name,
                "table": table, "unit": unit, "install_directory": root,
                "connection_mark": p["unix_uid"], "policy": p}
    return {"firewall.nft": "\n".join(nft) + "\n", "dnsmasq.conf": "\n".join(dns) + "\n",
            "resolv.conf": f"nameserver {p['resolver']}\noptions timeout:2 attempts:2\n",
            firewall: firewall_text, dnsunit: dns_text, "50-egress.conf": dropin,
            "manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n"}


def compile_observe(p: dict) -> dict[str, str]:
    """All-accept discovery, independent of daemon and its DNS configuration."""
    tag = hashlib.sha256(p["profile_uid"].encode()).hexdigest()[:12]
    name, table = f"mc-{tag}", f"mc_egress_{tag}"
    root = f"/etc/mrcalld/egress/{name}"
    observer = f"mrcall-observe-{tag}.service"
    refresh = f"mrcall-observe-refresh-{tag}.service"
    timer = refresh.removesuffix(".service") + ".timer"
    digest = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()
    marker = f"mrcall mode=observe policy={digest}"
    nft = [f"add table inet {table}", f"delete table inet {table}",
           f"table inet {table} {{", f' comment "{marker}"',
           " counter outside_total { }", " counter outside_logged { }"]
    for i, _ in enumerate(p["endpoints"]):
        for family in (4, 6):
            nft.append(f" set e{i}_{family} {{ type ipv{family}_addr; size 4096; }}")
    nft.extend([" chain output {", "  type filter hook output priority 10; policy accept;",
                f"  meta skuid {p['unix_uid']} jump observe_{digest}", " }", f" chain observe_{digest} {{",
                "  ct direction reply counter accept"])
    for i, entry in enumerate(p["endpoints"]):
        for family, selector in ((4, "ip"), (6, "ip6")):
            for proto in ("tcp", "udp"):
                if entry[proto]:
                    ports = ", ".join(map(str, entry[proto]))
                    nft.append(f"  {selector} daddr @e{i}_{family} {proto} dport {{ {ports} }} counter accept")
    # All other protocols are accepted too; discovery concerns TCP/UDP only.
    nft.extend(["  meta l4proto { tcp, udp } counter name outside_total",
                f'  meta l4proto {{ tcp, udp }} limit rate 10/second burst 20 packets counter name outside_logged log prefix "mc-obs-{tag} " level info',
                "  counter accept", " }", "}"])
    manifest = {"status": "scratch-experiment-not-production-approved", "tenant": name,
                "table": table, "install_directory": root, "policy": p,
                "observe_marker": marker, "observe_chain": f"observe_{digest}", "log_prefix": f"mc-obs-{tag} "}
    return {"firewall.nft": "\n".join(nft) + "\n",
            "manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            observer: f"""[Unit]
Description=MrCall tenant observation {name}
After=nftables.service

[Service]
Type=oneshot
ExecStart=/usr/bin/flock -x {root}/observe.lock /usr/sbin/nft -f {root}/firewall.nft
RemainAfterExit=yes
# No dependency on the daemon; no removal or denial on observer failure.
""",
            refresh: f"""[Unit]
Description=MrCall observation candidate snapshot {name}
After=network.target {observer}

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/libexec/mrcall-egress/egress_observe.py refresh {root}/manifest.json
TimeoutStartSec=45
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths={root}
""",
            timer: f"""[Unit]
Description=MrCall observation candidate refresh timer {name}

[Timer]
OnActiveSec=1s
OnUnitActiveSec=60s
AccuracySec=1s
Unit={refresh}

[Install]
WantedBy=timers.target
"""}


def unique_fields(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError("duplicate JSON field")
        result[key] = value
    return result


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: egress_policy.py POLICY_JSON NEW_OUTPUT_DIRECTORY", file=sys.stderr)
        return 2
    try:
        raw = json.loads(Path(sys.argv[1]).read_text(), object_pairs_hook=unique_fields)
        artifacts = compile_policy(raw)
        target = Path(sys.argv[2])
        target.mkdir(mode=0o700, parents=False, exist_ok=False)
        for filename, content in artifacts.items():
            with (target / filename).open("x") as output:
                output.write(content)
        print("[egress] compile -> scratch artifacts written; no host changes")
        return 0
    except (PolicyError, ValueError, OSError):
        print("[egress] compile refused: invalid policy or output path; no host changes", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
