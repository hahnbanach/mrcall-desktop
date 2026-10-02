"""The two workflows of the model table, as files (brief D8, constraints on keys and spend).

`.github/workflows/model-resolution.yml` runs the paid daily job: on a
schedule before the billing server's 06:00 UTC refresh and on dispatch,
never on a pull request, one run at a time and never cancelled mid-way, with
the right to push the data branch, the key only from the repository's
secrets and only in a step's environment. `.github/workflows/release.yml`
embeds the published table before the engine is bundled and refuses a stale
or failing one. Whether a `push` trigger is present is deliberately not
pinned here: the plan's proof run adds one temporarily (plan, S5) and S8
checks it is gone before the merge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
SECRET = "${{ secrets.OPENROUTER_API_KEY }}"


def load(name: str) -> dict:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))  # YAML 1.1 reads a bare `on` as true
    return doc


def test_the_daily_job_runs_on_schedule_and_dispatch_never_on_a_pull_request():
    doc = load("model-resolution.yml")
    assert doc["on"]["schedule"] == [{"cron": "17 5 * * *"}]
    assert "workflow_dispatch" in doc["on"]
    assert not {"pull_request", "pull_request_target"} & set(doc["on"])
    assert doc["concurrency"]["cancel-in-progress"] is False and doc["concurrency"]["group"]
    assert doc["permissions"] == {"contents": "write"}


def test_the_daily_job_reads_the_key_from_secrets_only_in_a_steps_environment():
    text = (WORKFLOWS / "model-resolution.yml").read_text(encoding="utf-8")
    steps = load("model-resolution.yml")["jobs"]["publish"]["steps"]
    for step in steps:
        assert "secrets." not in str(step.get("run", "")), step.get("name")
        assert "secrets." not in str(step.get("with", "")), step.get("name")
    users = [s for s in steps if SECRET in (s.get("env") or {}).values()]
    assert [s["name"] for s in users] == [
        "Require the OpenRouter key",
        "Resolve, verify and publish",
    ]
    assert text.count("secrets.") == 2
    for step in steps:  # the value is only ever tested for emptiness: never echoed, never argv
        run = step.get("run", "")
        assert run.count("$OPENROUTER_API_KEY") == run.count('[ -z "$OPENROUTER_API_KEY" ]')


def test_the_daily_job_checks_out_the_data_branch_and_uploads_its_report():
    steps = load("model-resolution.yml")["jobs"]["publish"]["steps"]
    checkouts = [
        s.get("with", {}) for s in steps if str(s.get("uses", "")).startswith("actions/checkout")
    ]
    assert {"ref": "model-table", "path": "model-table"} in checkouts and len(checkouts) == 2
    python = next(s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert python["with"]["python-version"] == "3.11"
    run = next(s for s in steps if s.get("name") == "Resolve, verify and publish")["run"]
    assert "engine/scripts/model_table_job.py" in run and "--data model-table" in run
    assert "--dry-run" not in run
    upload = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert upload["if"] == "always()" and upload["with"]["path"] == "model-table-report.md"
    # The memory roles' measurement is the M9 corpus runner: a pytest module.
    install = next(s for s in steps if s.get("name") == "Install the engine")["run"]
    assert "pip install -e engine pytest pytest-asyncio" in install


def test_a_release_embeds_the_published_table_before_bundling_and_refuses_a_stale_one():
    steps = load("release.yml")["jobs"]["build-engine"]["steps"]
    names = [s.get("name", s.get("uses")) for s in steps]
    embed = names.index("Embed the published model table (refuse a stale or failing copy)")
    assert embed < names.index("Build sidecar (PyInstaller)")
    run = steps[embed]["run"]
    assert "git fetch --no-tags --depth=1 origin model-table" in run
    for name in ("table.json", "snapshot.json"):
        assert f"git show FETCH_HEAD:v1/{name} > zylch/llm/roles/{name}" in run
    assert "python scripts/model_table_release.py --max-age-days 14" in run
    assert run.splitlines()[0] == "set -euo pipefail"
