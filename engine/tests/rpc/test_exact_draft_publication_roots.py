"""Root aliases share the same durable publication reservation."""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from tests.rpc.test_exact_draft_publication import (
    setup as publication_setup,
    Mailbox,
    OWNER,
    UID,
    ID,
    ROOT,
    service,
    snapshot,
    effects,
    DraftOperations,
)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from publication_setup.__wrapped__(tmp_path, monkeypatch)


@pytest.mark.parametrize("alias", [" " + ROOT + " ", "\r\n\t" + ROOT + "\r\n "])
def test_concurrent_root_aliases_share_reservation(setup, alias):
    row, path = setup
    inventoried = threading.Event()
    release = threading.Event()

    class ConcurrentMailbox(Mailbox):
        def inventory(self):
            result = super().inventory()
            if self.reads == 1:
                inventoried.set()
                assert release.wait(timeout=5)
            return result

    def publish(root, operation):
        return service.publish(
            OWNER,
            UID,
            ID,
            snapshot(row),
            root,
            operation,
            lambda: (OWNER, UID),
            mailbox_factory=ConcurrentMailbox,
        )

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(publish, alias, "alias")
        try:
            assert inventoried.wait(timeout=5)
            second = pool.submit(publish, ROOT, "canonical").result(timeout=5)
            assert second["cause"] == "operation_held"
            assert second["root"] == ROOT
            assert second["operation_id"] == "alias"
        finally:
            release.set()
        assert first.result(timeout=5)["ok"]
    assert effects(path) == 1
    operation = DraftOperations().read(UID, "alias")
    assert operation["canonical_root"] == ROOT
    assert DraftOperations().read(UID, "canonical") is None
    assert publish(ROOT, "after")["ok"]
    assert effects(path) == 1


def test_wrong_thread_refused_before_reservation(setup):
    row, path = setup
    answer = service.publish(
        OWNER, UID, ID, snapshot(row), " <other@example.test> ", "wrong", lambda: (OWNER, UID)
    )
    assert answer["cause"] == "draft_binding_mismatch"
    assert answer["effect_certainty"] == "not-dispatched"
    assert effects(path) == 0
    assert DraftOperations().read(UID, "wrong") is None
