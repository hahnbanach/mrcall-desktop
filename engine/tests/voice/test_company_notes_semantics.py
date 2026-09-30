"""Synthetic boundaries between public facts, staff workflows and question intent."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from .test_company_notes import SOURCE, output, provider, setup, unit_id
from zylch.services.voice import company_notes as notes


@pytest.mark.parametrize(
    "directive",
    [
        "Create a work item for every inquiry.",
        "All requests have a task assigned for follow-up.",
        "The operator must verify the request before closure.",
        "Each request is considered completed once confirmation is recorded.",
        "Mark the order complete after checking receipt.",
        "Check whether the customer received the package.",
        "The staff should update the record after fulfillment.",
        "How to handle inquiries: First gather the request fields, then propose a next step.",
        "DO NOT invent or reuse an inquiry-specific document.",
        "Explain that, after registration, enter the reference field.",
        "If the request is unsupported, make the reply brief: thank, decline, close.",
        "If the request is unsupported, the response should be brief: decline and close.",
        "If the request is unsupported, the response is\nshort: thank, decline, close.",
        "Founders: Person A and Person B.",
        "If the purchase control is hidden, suggest scrolling and selecting the item.",
        "Variants observed: compact; large.",
        "Observed variants: compact; large.",
    ],
)
@pytest.mark.parametrize("section", ["actions", "details"])
def test_internal_workflow_is_filtered_before_conversion_and_after_selection(
    tmp_path, monkeypatch, directive, section
):
    source = SOURCE + " " + directive
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    selected_id = unit_id(source, directive)
    if section == "actions":
        payload[section] = [[selected_id]]
    else:
        payload[section].append(
            {
                "ids": [selected_id],
                "category": "process",
                "key": "fulfillment_checks",
                "aliases": ["fulfillment checks"],
            }
        )
    calls, _ = provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert directive not in calls[0]["messages"][0]["content"]
    assert directive not in view.context
    assert "Some source details are ambiguous" in view.omissions
    assert notes.company_note_detail(profile, snapshot, "fulfillment checks").status == "missing"
    artifact = json.loads((profile / notes.ARTIFACT).read_text())
    assert directive not in json.dumps(artifact)


def test_restricted_workflow_continuation_omits_whole_service_group():
    source = (
        "We repair widgets. Check the assigned task before accepting a repair. "
        "We paint blue widgets."
    )
    selection = notes.Selection.model_validate(
        {
            "identity": None,
            "services": [[0, 1], [2]],
            "qualifications": [],
            "exclusions": [],
            "actions": [],
            "details": [],
            "missing": [],
        }
    )
    materialized = notes._materialize(selection, notes._units(source), source)
    notes._validate(materialized, source)
    assert [claim.text for claim in materialized.services] == ["We paint blue widgets."]
    assert "ambiguous" in materialized.missing


def test_public_process_with_coaching_continuation_is_omitted_as_one_group(
    tmp_path, monkeypatch
):
    detail = (
        "Brochures are available on request. DO NOT invent or reuse an inquiry document. "
        "Explain that, after registration, enter the reference field."
    )
    source = SOURCE + " " + detail
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["details"].append(
        {
            "ids": [3, 4, 5],
            "category": "process",
            "key": "brochure_requests",
            "aliases": ["how to request brochures"],
        }
    )
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert notes.company_note_detail(profile, snapshot, "how to request brochures").status == "missing"
    assert "Some source details are ambiguous" in view.omissions


def test_public_customer_action_remains_exact_and_qualified(tmp_path, monkeypatch):
    action = "Customers can request a brochure. Brochures require an appointment."
    source = SOURCE + " " + action
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["actions"] = [[3, 4]]
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    start, end = next((start, end) for section, start, end in view.included_spans if section == "actions")
    assert source[start:end] == action
    assert action in view.context


def test_task_management_service_is_not_an_operator_instruction(tmp_path, monkeypatch):
    service = "Acme offers task management software."
    source = SOURCE + " " + service
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["services"].append([3])
    calls, _ = provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert service in calls[0]["messages"][0]["content"]
    assert service in view.context


@pytest.mark.parametrize("keep_supported", [False, True])
def test_untimed_process_never_matches_arrival_time_aliases(
    tmp_path, monkeypatch, keep_supported
):
    detail = "Brochures are available on request."
    source = SOURCE + " " + detail
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    temporal = ["when will brochures arrive", "quando arrivano le brochure", "quanto tempo per la brochure"]
    ordinary = [
        "how to request brochures",
        "come richiedere brochure",
        "come posso avere una brochure",
        "come ricevo la brochure",
        "come posso ricevere la brochure",
    ]
    payload["details"].append(
        {
            "ids": [3],
            "category": "process",
            "key": "brochure_requests",
            "aliases": temporal + (ordinary if keep_supported else []),
        }
    )
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert "Some source details are ambiguous" in view.omissions
    for question in temporal:
        assert notes.company_note_detail(profile, snapshot, question).status == "missing"
    for question in ordinary:
        result = notes.company_note_detail(profile, snapshot, question)
        assert result.status == ("supported" if keep_supported else "missing")
        if keep_supported:
            assert result.text == detail == source[result.start : result.end]
    exact = notes.company_note_detail_exact(
        profile, snapshot, "process", "brochure_requests", view.source_hash
    )
    assert exact.status == ("supported" if keep_supported else "missing")
    for question in ("Che servizi offrite?", "What services do you offer?", "Cosa fate?"):
        assert notes.company_note_detail(profile, snapshot, question).status == "missing"


@pytest.mark.parametrize("selected", [False, True])
def test_unselected_exclusion_is_an_explicit_gap(tmp_path, monkeypatch, selected):
    exclusion = "Red widgets are not accepted. This includes red accessories."
    source = SOURCE + " " + exclusion
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    if selected:
        payload["exclusions"] = [[3, 4]]
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    gap = "Service exclusions unavailable in initial context"
    assert (gap in view.context) is not selected
    assert (gap in view.omissions) is not selected
    assert (exclusion in view.context) is selected


def test_dispatch_frequency_does_not_support_an_arrival_time_alias(tmp_path, monkeypatch):
    profile, snapshot = setup(tmp_path, monkeypatch)
    payload = output()
    payload["details"][0]["aliases"].extend(
        ["when will widgets arrive", "quando arrivano i prodotti"]
    )
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert notes.company_note_detail(profile, snapshot, "quando consegnate").status == "supported"
    assert notes.company_note_detail(profile, snapshot, "when will widgets arrive").status == "missing"
    assert notes.company_note_detail(profile, snapshot, "quando arrivano i prodotti").status == "missing"


def test_selected_italian_size_paraphrases_keep_exact_format_fact(tmp_path, monkeypatch):
    detail = "Brochure format is A5."
    source = SOURCE + " " + detail
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["details"].append(
        {
            "ids": [3],
            "category": "qualification",
            "key": "brochure_format",
            "aliases": ["formato della brochure", "quali dimensioni ha la brochure"],
        }
    )
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    for question in ("Formato della brochure?", "Quali dimensioni ha la brochure?"):
        result = notes.company_note_detail(profile, snapshot, question)
        assert result.status == "supported"
        assert result.text == detail == source[result.start : result.end]
        assert (result.category, result.key) == ("qualification", "brochure_format")


@pytest.mark.parametrize("alias", ["come posso", "posso avere", "come posso ricevere"])
def test_modal_request_without_subject_is_not_a_specific_alias(tmp_path, monkeypatch, alias):
    profile, snapshot = setup(tmp_path, monkeypatch)
    payload = output()
    payload["details"][0]["aliases"] = [alias]
    provider(monkeypatch, payload)
    assert asyncio.run(notes.prepare_company_notes(profile, snapshot)).status == "unavailable"


@pytest.mark.parametrize("tampering", ["instruction", "timing_alias", "exclusion_gap", "detail_gap"])
def test_cached_artifact_revalidates_semantic_filters(tmp_path, monkeypatch, tampering):
    directive = "Each request is considered completed once confirmation is recorded."
    source = SOURCE + " " + directive
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    provider(monkeypatch, output(source))
    assert asyncio.run(notes.prepare_company_notes(profile, snapshot)).status == "supported"
    artifact = profile / notes.ARTIFACT
    payload = json.loads(artifact.read_text())
    if tampering == "instruction":
        payload["notes"]["actions"] = [notes._units(source)[3].model_dump()]
    elif tampering == "timing_alias":
        payload["notes"]["details"][0]["claim"] = notes._units(source)[1].model_dump()
        payload["notes"]["details"][0]["aliases"] = ["when will widgets arrive"]
    elif tampering == "detail_gap":
        payload["notes"]["details"] = []
    else:
        payload["notes"]["missing"].remove("exclusion")
    artifact.write_text(json.dumps(payload))
    assert notes.current_company_notes(profile, snapshot).status == "unavailable"
    assert notes.company_note_detail(profile, snapshot, "weekly delivery").status == "unavailable"


def test_prompt_and_schema_change_invalidate_previous_view(tmp_path, monkeypatch):
    profile, snapshot = setup(tmp_path, monkeypatch)
    provider(monkeypatch, output())
    with monkeypatch.context() as previous:
        previous.setattr(notes, "PROMPT_VERSION", 7)
        previous.setattr(notes, "SCHEMA_VERSION", 5)
        old = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert old.status == "supported"
    assert notes.current_company_notes(profile, snapshot).status == "unavailable"
    new = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert new.status == "supported"
    assert old.source_hash == new.source_hash
    assert old.cache_key != new.cache_key


@pytest.mark.parametrize("include_history", [False, True])
def test_only_required_qualifiers_join_current_service_group(
    tmp_path, monkeypatch, include_history
):
    source = (
        SOURCE + " Acme repairs green widgets. Green widgets require an appointment. "
        "Variants observed: compact; large."
    )
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["services"].append([3, 4, 5] if include_history else [3, 4])
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert ("Acme repairs green widgets." in view.context) is not include_history
    assert ("Green widgets require an appointment." in view.context) is not include_history
    assert "Variants observed" not in view.context
    assert ("Some source details are ambiguous" in view.omissions) is include_history


@pytest.mark.parametrize(
    "wrapper, supported",
    [
        ("{}", True),
        ("```json\n{}\n```", True),
        (" \n```json\r\n{}\r\n```\n ", True),
        ("Here is the result:\n```json\n{}\n```", False),
        ("```json\n{}\n```\nExplanation follows.", False),
        ("```\n{}\n```", False),
        ("```javascript\n{}\n```", False),
        ("```json\n{}\n```\n```json\n{{}}\n```", False),
        ("```json\n{}", False),
    ],
)
def test_single_json_fence_uses_normal_preparation_and_validation(
    tmp_path, monkeypatch, wrapper, supported
):
    source = SOURCE + " Founders: Person A and Person B."
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["actions"] = [[3]]
    raw = wrapper.format(json.dumps(payload))
    calls = []

    class Client:
        async def create_message(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text=raw)]
            )

    monkeypatch.setattr(notes, "make_llm_client", lambda model: Client())
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == ("supported" if supported else "unavailable")
    assert len(calls) == 1
    if supported:
        assert "Founders" not in view.context
        assert "Some source details are ambiguous" in view.omissions
        assert notes.current_company_notes(profile, snapshot) == view
    else:
        assert not (profile / notes.ARTIFACT).exists()


@pytest.mark.parametrize("filtered", [False, True])
def test_zero_materialized_details_always_report_gap(tmp_path, monkeypatch, filtered):
    source = SOURCE + " Founders: Person A and Person B."
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["details"] = []
    if filtered:
        payload["details"] = [
            {
                "ids": [3],
                "category": "other",
                "key": "founder_list",
                "aliases": ["founder list"],
            }
        ]
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert "Acme sells blue widgets." in view.context
    assert "Service details unavailable" in view.context
    assert "Service details unavailable" in view.omissions
    assert notes.company_note_detail(profile, snapshot, "weekly delivery").status == "missing"


@pytest.mark.parametrize(
    "heading",
    [
        "## Specifications (facts, do not invent others)",
        "## Products (data, do not invent additional facts)",
        "## Specifiche (dati, non inventarne altri)",
    ],
)
def test_pure_leading_meta_heading_keeps_ids_and_exact_qualified_body(heading):
    body = "- Blue widgets support customization. Only blue widgets are accepted."
    source = SOURCE + "\n\n" + heading + "\n" + body
    units = notes._units(source)
    assert len(units) == 5
    assert units[3].text == "- Blue widgets support customization."
    assert units[3].start == source.index("- Blue widgets")
    payload = output(source)
    payload["details"] = [
        {"ids": [3, 4], "category": "qualification", "key": "widget_customization",
         "aliases": ["personalize blue widgets", "posso personalizzare widget"]}
    ]
    selected = notes._materialize(notes.Selection.model_validate(payload), units, source)
    notes._validate(selected, source)
    claim = selected.details[0].claim
    assert claim.text == body == source[claim.start : claim.end]
    assert claim.end == len(source)
    assert selected.details[0].aliases == payload["details"][0]["aliases"]


@pytest.mark.parametrize(
    "heading",
    [
        "## Products only for appointments (facts, do not invent others)",
        "## Products 100 (facts, do not invent others)",
        "## Historical products (facts, do not invent others)",
        "## Products (only blue widgets; do not invent others)",
        "## Products (facts, do not invent others) Limited availability.",
    ],
)
def test_factual_or_qualified_headings_are_never_trimmed(heading):
    source = heading + "\n- Blue widgets support customization."
    unit = notes._units(source)[0]
    assert unit.start == 0 and unit.text.startswith(heading)
    assert unit.text == source[: unit.end]


def test_heading_trim_never_removes_historical_or_midspan_qualifiers():
    source = SOURCE + "\n\n## Products (facts, do not invent others)\n" + (
        "- Blue widgets support customization. Variants observed: compact; large."
    )
    payload = output(source)
    payload["details"] = [
        {"ids": [3, 4], "category": "qualification", "key": "widget_options",
         "aliases": ["widget options"]}
    ]
    result = notes._materialize(notes.Selection.model_validate(payload), notes._units(source), source)
    assert not result.details and "ambiguous" in result.missing
    source = "Blue widgets support customization.\n\n## Products (facts, do not invent others)\n- Only blue widgets are accepted."
    units = notes._units(source)
    assert len(units) == 2 and units[1].text == "- Only blue widgets are accepted."
    selection = notes.Selection.model_validate(
        {"identity": None, "services": [[0, 1]], "qualifications": [],
         "exclusions": [], "actions": [], "details": [], "missing": []}
    )
    result = notes._materialize(selection, units, source)
    assert not result.services and "ambiguous" in result.missing


@pytest.mark.parametrize("value", ["persona", "Assistant persona instructions", "persona: friendly"])
def test_standalone_persona_is_still_restricted(value):
    assert notes._DENIED.search(value)
