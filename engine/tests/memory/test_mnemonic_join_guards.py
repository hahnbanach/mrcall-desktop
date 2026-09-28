"""The join's narrower guards: what an import refuses, what it leaves alone, what recovery ignores.

On the same two real company stores as ``test_mnemonic_join_crashes.py``
(its ``world`` fixture): an ordinary failure inside the import leaves no
company fenced; the import refuses a fence of another company or another
destination; a blob id the destination already holds keeps the destination's
own sentences; recovery touches only a fence placed for the destination the
``.env`` names.
"""

from __future__ import annotations

import pytest

from zylch.memory import join_import, join_recover
from zylch.memory.company_key import current_company_key
from zylch.memory.join import join
from zylch.memory.mnemonic import fence
from zylch.memory.mnemonic.fence import ACCEPTED, COMPLETED, FENCED, RELEASED
from zylch.services import project_join
from zylch.services.settings_io import update_env
from zylch.storage import database as dbm

from . import seeding
from .join_env import count, destination, env_value, phases, receipts, rows, store_digest
from .mnemonic_env import COMPANY_A, COMPANY_B, OWNER_A
from .test_mnemonic_join_crashes import LUCA_LATER, completed_import, imported
from . import test_mnemonic_join_crashes as crashes

world = crashes.world  # the two stores and the joining profile

COMPANY_C = "CCCCCCCCCCCCCCCCCCCCCC"


def test_an_ordinary_failure_inside_the_import_releases_the_fence_and_clears_the_setting(world, monkeypatch):
    def diverging(*args, **kwargs):
        raise RuntimeError("the two project histories diverge")

    monkeypatch.setattr(project_join, "merge_projects", diverging)
    before = store_digest(COMPANY_B)

    with pytest.raises(RuntimeError, match="diverge"):
        join(COMPANY_B)

    assert phases(COMPANY_A) == [RELEASED] and env_value("MEMORY_JOIN_TO") == ""
    assert current_company_key() == COMPANY_A and env_value("MEMORY_KEY") == COMPANY_A
    assert store_digest(COMPANY_B) == before and receipts() == []


def test_an_import_refuses_a_fence_of_another_company_or_for_another_destination(world):
    other = fence.place(COMPANY_A, [OWNER_A], COMPANY_C)
    before = store_digest(COMPANY_B)

    with pytest.raises(join_import.ImportRefused, match="another destination"):
        imported(other)
    engine = join_recover.open_store(COMPANY_B)
    try:
        with pytest.raises(join_import.ImportRefused, match="no join fence of this attempt"):
            join_import.import_into(
                dbm.current_memory_engine(), engine, other,
                source_key=COMPANY_B, destination_key=COMPANY_C,
            )
    finally:
        engine.dispose()

    assert store_digest(COMPANY_B) == before and phases(COMPANY_A) == [FENCED]


def test_a_blob_the_destination_already_holds_keeps_its_own_sentences(world):
    completed_import()
    kept = rows(COMPANY_B, "SELECT id FROM blob_sentences WHERE blob_id = ? ORDER BY id", [world.luca])
    current = world.storage.get_blob(world.luca, OWNER_A)
    seeding.update_blob(
        world.storage, world.luca, OWNER_A, LUCA_LATER + "\n- paid by transfer", "seed",
        expected_updated_at=current["updated_at"],
    )

    assert completed_import()["retained"] == 1

    assert rows(COMPANY_B, "SELECT id FROM blob_sentences WHERE blob_id = ? ORDER BY id", [world.luca]) == kept


def test_recovery_leaves_a_fence_placed_for_another_destination(world):
    destination(COMPANY_C)
    other = fence.place(COMPANY_A, [OWNER_A], COMPANY_C)
    update_env({"MEMORY_JOIN_TO": COMPANY_B})

    assert join_recover.recover() == {"state": "before_key", "action": "cleared"}
    assert env_value("MEMORY_JOIN_TO") == "" and phases(COMPANY_A) == [FENCED]

    assert fence.move(other, FENCED, ACCEPTED)
    update_env({"MEMORY_KEY": COMPANY_B, "MEMORY_KEY_SOURCE": "join", "MEMORY_JOIN_FROM": COMPANY_A})

    assert join_recover.recover() == {"state": "after_key", "completed": False}
    assert phases(COMPANY_A) == [ACCEPTED] and COMPLETED not in phases(COMPANY_A)
    assert count(COMPANY_C, "blobs") == 0
