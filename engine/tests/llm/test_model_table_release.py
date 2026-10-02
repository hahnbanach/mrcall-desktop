"""The release gate: `release.yml` embeds the published table only when it is fresh and passes.

`scripts/model_table_release.py` checks the copies `release.yml` fetched
from the `model-table` data branch into the build: the static gates against
this build's requirements, and a snapshot read at most 14 days ago (the job
republishes it on every run that publishes). The documents are the
synthetic world of `model_table_world.py` resolved by hand.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone

import pytest

from .model_table_world import SCRIPTS, World, load_job, measured, published, requirements

job = load_job()
READ = datetime(2026, 10, 14, 5, 17, 0, tzinfo=timezone.utc)  # the world's read_at
DAY = timedelta(days=1)


def load_release():
    spec = importlib.util.spec_from_file_location(
        "model_table_release", SCRIPTS / "model_table_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_release()


@pytest.fixture
def roles(tmp_path):
    req = requirements()
    files = published(job, World(), req, measured())
    (tmp_path / "requirements.json").write_text(json.dumps(req), encoding="utf-8")
    for name in ("table.json", "snapshot.json"):
        (tmp_path / name).write_bytes(files[name])
    return tmp_path


def test_a_fresh_copy_passing_the_gates_is_embedded(roles, capsys):
    assert release.main(["--roles", str(roles)], now=READ + 14 * DAY) == 0
    out = capsys.readouterr().out
    assert "model table embedded" in out and "read at 2026-10-14T05:17:00Z" in out


def test_a_copy_older_than_14_days_is_refused(roles, capsys):
    assert release.main(["--roles", str(roles)], now=READ + 14 * DAY + timedelta(hours=1)) == 1
    assert "more than 14 days ago" in capsys.readouterr().out


def test_a_copy_failing_the_gates_is_refused(roles, capsys):
    table = json.loads((roles / "table.json").read_text(encoding="utf-8"))
    table["presets"]["economy"]["roles"]["CHAT"]["ranking"] = []  # restamped: only coverage fails
    (roles / "table.json").write_text(json.dumps(job.rm.gates.stamped(table)), encoding="utf-8")
    assert release.main(["--roles", str(roles)], now=READ) == 1
    assert "coverage: economy / CHAT has no ranking" in capsys.readouterr().out


def test_a_copy_the_gates_cannot_read_is_refused(roles, capsys):
    (roles / "snapshot.json").write_text("<html>502</html>", encoding="utf-8")
    assert release.main(["--roles", str(roles)], now=READ) == 1
    assert "::error::model table refused" in capsys.readouterr().out


def test_the_age_limit_may_only_be_lowered(roles, capsys):
    with pytest.raises(SystemExit):
        release.main(["--roles", str(roles), "--max-age-days", "15"], now=READ)
    assert "at most 14 days" in capsys.readouterr().err
    assert release.main(["--roles", str(roles), "--max-age-days", "1"], now=READ + 2 * DAY) == 1
