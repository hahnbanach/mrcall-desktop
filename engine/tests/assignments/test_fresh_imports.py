"""Production entry modules load in fresh interpreters without Storage preloads."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ENGINE = Path(__file__).resolve().parents[2]
MODULES = [
    "zylch.email.imap_client", "zylch.services.sync_service", "zylch.email.mailbox_probe",
    "zylch.services.contextual_email_policy",
    "zylch.services.task_assignment_email_effect", "zylch.services.task_assignment_draft_transaction",
    "zylch.services.task_assignment_enrollment", "zylch.services.project_store",
    "zylch.services.solve_tools", "zylch.tools.gmail_tools",
    "zylch.cli.main", "zylch.rpc.server_ws", "zylch.rpc.server",
]


@pytest.mark.parametrize("entry", [*MODULES, "enrollment-script", "cli-help"])
def test_fresh_supported_entry_import(entry, tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), ZYLCH_HOME=str(tmp_path / "zylch"),
               MEMORY_DB_DIR=str(tmp_path / "memory"), PYTHONPATH=str(ENGINE))
    for key in ("ZYLCH_PROFILE_DIR", "OWNER_ID", "EMAIL_ADDRESS", "EMAIL_PASSWORD"):
        env.pop(key, None)
    code = '''
import importlib, json, runpy, socket, sys
from pathlib import Path
def forbid_network(*args, **kwargs):
    raise AssertionError("Fresh import attempted external network")
socket.socket.connect = forbid_network
socket.create_connection = forbid_network
entry = sys.argv[1]
if entry == "enrollment-script":
    result = runpy.run_path("scripts/server/assignment_enroll.py", run_name="fresh_import_probe")
    assert callable(result["install"])
    loaded = str(Path("scripts/server/assignment_enroll.py").resolve())
elif entry == "cli-help":
    from click.testing import CliRunner
    from zylch.cli.main import cli
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    loaded = importlib.import_module("zylch.cli.main").__file__
else:
    loaded = importlib.import_module(entry).__file__
assert str(Path(loaded).resolve()).startswith(str(Path.cwd().resolve()) + "/")
print(json.dumps({"entry": entry, "loaded": loaded, "network": "forbidden"}))
'''
    result = subprocess.run([sys.executable, "-c", code, entry], cwd=ENGINE, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads(result.stdout.splitlines()[-1])
    assert proof["entry"] == entry
    print(json.dumps({"argv": result.args, "cwd": str(ENGINE), "env": {key: env[key] for key in ("PYTHONPATH", "HOME", "ZYLCH_HOME", "MEMORY_DB_DIR")},
                      "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}))
