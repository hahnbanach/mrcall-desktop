"""The exact CAS must contend with the released storage send-claim writer."""

from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from tests.rpc import test_exact_drafts as exact_tests

from zylch.storage.storage import Storage
from zylch.storage.models import Draft
from zylch.storage import database as db
from zylch.services.exact_draft_transaction import locked_row, session
from zylch.services.task_assignment_types import AssignmentError

OWNER, ID, row = exact_tests.OWNER, exact_tests.ID, exact_tests.row


def test_released_send_claim_waits_for_exact_delete(row):
    started = threading.Event()

    def claim():
        started.set()
        return Storage.get_instance().claim_draft_for_send(OWNER, ID)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with locked_row(OWNER, ID, row):
            future = pool.submit(claim)
            assert started.wait(2)
            assert not future.done()
            with session() as current:
                current.delete(current.query(Draft).filter_by(owner_id=OWNER, id=ID).one())
        assert future.result(timeout=5) is False


def test_released_claim_wins_before_exact_cas(row):
    assert Storage.get_instance().claim_draft_for_send(OWNER, ID)
    with pytest.raises(AssignmentError):
        with locked_row(OWNER, ID, row):
            pytest.fail("Stale exact snapshot admitted after released sender claim")
    assert Storage.get_instance().get_draft(OWNER, ID)["status"] == "sending"


@pytest.mark.parametrize(
    "field,value", [("owner_id", "other@example.test"), ("body", "changed"), ("status", "sent")]
)
def test_full_row_compare_rejects_changed_authority_or_content(row, field, value):
    with db.get_session() as current:
        setattr(current.query(Draft).filter_by(id=ID).one(), field, value)
    with pytest.raises(AssignmentError):
        with locked_row(OWNER, ID, row):
            pytest.fail("Changed persisted row admitted")
