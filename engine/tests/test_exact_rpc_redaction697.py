from copy import deepcopy

import pytest

from zylch.rpc.dispatch import _redact_params


@pytest.mark.parametrize("method", [
    "drafts.publish_review", "drafts.operation_status", "drafts.retire_sent_mirror",
    "drafts.operator_send_inspect", "drafts.send_operator",
])
def test_exact_draft_binding_logs_preserve_only_parameter_names(method):
    params = {"binding": {"source": {"from_email": "PRIVATE_SENTINEL@example.test"}},
              "draft_id": "PRIVATE_DRAFT_SENTINEL"}
    before = deepcopy(params)
    result = _redact_params(method, params)
    assert set(result) == set(params)
    assert "PRIVATE_SENTINEL" not in repr(result)
    assert "PRIVATE_DRAFT_SENTINEL" not in repr(result)
    assert params == before
