"""Ripulisce il .env del profilo attivo riscrivendolo tutto col quoter nuovo.

Perché serve: versioni vecchie di settings_io usavano shlex.quote, che
per valori con apostrofi generava sintassi shell (`'"'"'`) che
python-dotenv non parsa. Un save successivo col quoter nuovo aggiunge
la nuova riga ma non rimuove la vecchia, lasciando linee malformed
nel file → warning "could not parse statement at line N" ad ogni
avvio del sidecar.

Questo script:
  1. Legge il .env via python-dotenv (salta le linee malformed — è
     quello che fa già il sidecar, i valori rotti sono persi comunque).
  2. Lo riscrive da zero usando ordering dello schema settings, con
     il _quote corretto.
  3. Mostra quante linee aveva il vecchio file e quante il nuovo.

Uso:
  ZYLCH_PROFILE=mario.alemi@cafe124.it venv/bin/python scripts/repair_env.py          # dry-run
  ZYLCH_PROFILE=mario.alemi@cafe124.it venv/bin/python scripts/repair_env.py --apply
"""
import argparse
import os
import shutil
import sys
from datetime import datetime

if not os.environ.get("ZYLCH_PROFILE_DIR"):
    profile = os.environ.get("ZYLCH_PROFILE", "")
    if not profile:
        print("set ZYLCH_PROFILE", file=sys.stderr)
        sys.exit(2)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from zylch.cli.profiles import activate_profile

    activate_profile(profile)

from dotenv import dotenv_values  # noqa: E402

from zylch.services.settings_io import _quote  # noqa: E402
from zylch.services.settings_schema import KNOWN_KEYS  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    env_path = os.path.join(os.environ["ZYLCH_PROFILE_DIR"], ".env")
    if not os.path.isfile(env_path):
        print(f"no .env at {env_path}", file=sys.stderr)
        return 1

    with open(env_path, "r", encoding="utf-8") as f:
        old_text = f.read()
    old_lines = old_text.splitlines()
    old_count = len(old_lines)

    # dotenv skips malformed lines silently and returns only the ones it
    # could parse. Exactly what we want.
    values = dict(dotenv_values(env_path))
    parsed_count = len(values)

    # Partition keys: known-schema ones first (ordered), then the rest
    # (user may have added custom entries via `zylch init`).
    new_text_parts = []
    for key in KNOWN_KEYS:
        if key in values:
            new_text_parts.append(f"{key}={_quote(values[key])}")
    extras = [k for k in values if k not in KNOWN_KEYS]
    if extras:
        new_text_parts.append("")
        new_text_parts.append("# extra keys")
        for key in sorted(extras):
            new_text_parts.append(f"{key}={_quote(values[key])}")
    new_text = "\n".join(new_text_parts) + "\n"
    new_lines = new_text.splitlines()

    print(f"old .env: {old_count} lines on disk")
    print(f"dotenv parsed cleanly: {parsed_count} keys")
    print(f"lines that would be dropped (malformed / comments): {old_count - len(new_lines)}")
    print(f"new .env: {len(new_lines)} lines")
    print()

    if not args.apply:
        print("--- DRY-RUN preview of the NEW .env (first 40 lines) ---")
        for i, line in enumerate(new_lines[:40], 1):
            # Never print actual values — just key/length for safety.
            if "=" in line and not line.startswith("#"):
                k = line.split("=", 1)[0]
                print(f"{i:3d}: {k}=… ({len(line)} chars on this line)")
            else:
                print(f"{i:3d}: {line}")
        if len(new_lines) > 40:
            print(f"... +{len(new_lines) - 40} more")
        print()
        print(">>> re-run with --apply to rewrite.")
        return 0

    # Apply with timestamped backup.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{env_path}.bak-{stamp}"
    shutil.copy2(env_path, backup)
    tmp = env_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, env_path)
    print(f"backup saved: {backup}")
    print("rewritten. restart the sidecar (Cmd+Q + ./start.sh) to pick it up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
