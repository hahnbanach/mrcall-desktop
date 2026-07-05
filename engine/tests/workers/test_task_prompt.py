"""Unit tests for the pure task-detection prompt assembly (P4 / FIX 1).

The whole point of :func:`build_detection_prompt` is that the CACHED system
block is byte-identical across different events for one owner, so the
ephemeral prompt cache actually hits. Per-event data must live ONLY in the
user message. These lock that contract (cases a–f from the plan).
"""

import hashlib

from zylch.workers.task_prompt import build_detection_prompt

# A template exercising every placeholder the live support@ prompt uses,
# plus {existing_task} (absent live, but the code must handle it).
TEMPLATE = (
    "You analyse events for {user_email}. Event type: {event_type}.\n"
    "EVENT: {event_data}\n"
    "MEMORY: {blob_context}\n"
    "OPEN TASK: {existing_task}\n"
    "CALENDAR: {calendar_context}\n"
    "Today is {today}."
)

POINTER = "(provided in the user message below)"
TODAY_POINTER = "(see the Datetime line at the end of the system prompt)"


def _common(**over):
    base = dict(
        trained_prompt=TEMPLATE,
        event_type="email",
        user_email="support@acme.io",
        personal_section="\nPERSONAL SECTION\n",
        today_str="2026-07-05",
    )
    base.update(over)
    return base


# ── (a) byte-identical system_text across two different events ──────────
def test_system_text_byte_identical_across_events():
    s1, _ = build_detection_prompt(
        event_data={"body": "First customer, order 111", "from": "a@x.io"},
        blob_context="blob-A",
        existing_task_context="task-A",
        calendar_context="cal-A",
        thread_history_section="THREAD A",
        **_common(),
    )
    s2, _ = build_detection_prompt(
        event_data={"body": "Totally different mail, order 999", "from": "b@y.io"},
        blob_context="blob-B",
        existing_task_context="task-B",
        calendar_context="cal-B",
        thread_history_section="THREAD B — much longer\nwith lines",
        **_common(),
    )
    assert s1 == s2, "system block must not vary with per-event data"
    # sanity: it is the hashable, stable prefix
    assert hashlib.sha256(s1.encode()).hexdigest() == hashlib.sha256(s2.encode()).hexdigest()


# ── (b) event body present in user_content, ABSENT from system_text ─────
def test_event_body_in_user_absent_from_system():
    body = "UNIQUE-BODY-MARKER order 42 refund please"
    s, u = build_detection_prompt(
        event_data={"body": body, "from": "a@x.io"},
        blob_context="blob",
        **_common(),
    )
    assert body in u
    assert body not in s


# ── (c) placeholders substituted (per-event → pointer) ──────────────────
def test_per_event_placeholders_become_pointer():
    s, _ = build_detection_prompt(event_data={"body": "x"}, blob_context="B", **_common())
    for name in ("{event_data}", "{blob_context}", "{existing_task}", "{calendar_context}"):
        assert name not in s, f"{name} still present in system block"
    # each per-event slot now points at the user message
    assert s.count(POINTER) == 4


# ── (d) template WITHOUT placeholders → system == template + personal ───
def test_template_without_placeholders():
    s, u = build_detection_prompt(
        trained_prompt="PLAIN TRAINED TEMPLATE — no placeholders",
        event_type="email",
        user_email="x@y.io",
        personal_section="\nPERSONAL\n",
        today_str="2026-07-05",
        event_data={"body": "hello"},
        existing_task_context="THE-EXISTING-TASK",
        calendar_context="THE-CALENDAR",
    )
    assert s == "PLAIN TRAINED TEMPLATE — no placeholders\nPERSONAL\n"
    # per-event data still reaches the model via the user message
    assert "THE-EXISTING-TASK" in u
    assert "THE-CALENDAR" in u


# ── (e) event_type/user_email literal; today → pointer ──────────────────
def test_literal_interpolation_and_today_pointer():
    s, _ = build_detection_prompt(event_data={"body": "x"}, **_common())
    assert "Event type: email." in s
    assert "support@acme.io" in s
    assert TODAY_POINTER in s
    assert "{today}" not in s and "2026-07-05" not in s  # date not baked into cache
    assert s.endswith("\nPERSONAL SECTION\n")


# ── (f) double-brace {{...}} forms handled too ──────────────────────────
def test_double_brace_forms_handled():
    tpl = "{{event_type}} for {{user_email}} :: {{event_data}} :: {{today}} :: {{blob_context}}"
    s, _ = build_detection_prompt(
        trained_prompt=tpl,
        event_type="calendar",
        user_email="u@z.io",
        personal_section="",
        today_str="2026-07-05",
        event_data={"k": 1},
    )
    assert s == f"calendar for u@z.io :: {POINTER} :: {TODAY_POINTER} :: {POINTER}"


# ── user_content structure preserved (thread note + sections) ───────────
def test_user_content_sections_and_thread_note():
    s, u = build_detection_prompt(
        event_data={"body": "hi"},
        blob_context="MEMBLOB",
        existing_task_context="EXTASK",
        calendar_context="CALCTX",
        thread_history_section="HISTORY-HERE",
        **_common(),
    )
    assert "HISTORY-HERE" in u
    assert "IMPORTANT — THREAD CONTEXT" in u  # the thread note rides with history
    assert "Memory context:\nMEMBLOB" in u
    assert "Existing task:\nEXTASK" in u
    assert "Calendar context:\nCALCTX" in u


def test_empty_sections_omitted_from_user_content():
    s, u = build_detection_prompt(event_data={"body": "hi"}, **_common())
    assert "Memory context:" not in u
    assert "Existing task:" not in u
    assert "Calendar context:" not in u
    assert "IMPORTANT — THREAD CONTEXT" not in u
