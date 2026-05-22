"""Every LLM request must carry the real current datetime.

Regression guard for the bug where task detection guessed the date from
the model's training cutoff ("today is May 20, pickup is tomorrow" on the
wrong day). The fix injects the datetime at the single LLMClient
chokepoint (covers task detection, memory, solve, chat, trainers, sweeps)
plus the chat-compaction summarizer that bypasses LLMClient.
"""

import asyncio
import datetime as _dt

from zylch.llm.client import LLMClient, _with_datetime, current_datetime_line

# ─── Fakes ────────────────────────────────────────────────────────────


class _FakeRaw:
    def __init__(self):
        self.stop_reason = "end_turn"
        self.content = []
        self.model = "test"
        self.usage = None


class _FakeMessages:
    def __init__(self):
        self.captured = None

    def create(self, **kwargs):
        self.captured = kwargs
        return _FakeRaw()


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def _client():
    c = LLMClient(transport="direct", api_key="x")
    fake = _FakeClient()
    c._client = fake
    return c, fake


def _system_text(sysv):
    if isinstance(sysv, str):
        return sysv
    return " ".join(b.get("text", "") for b in sysv)


# ─── current_datetime_line / _with_datetime ───────────────────────────


def test_current_datetime_line_has_today_and_weekday():
    line = current_datetime_line()
    assert "Datetime=" in line
    assert _dt.date.today().isoformat() in line
    assert _dt.datetime.now().strftime("%A") in line


def test_with_datetime_none_returns_line():
    out = _with_datetime(None)
    assert isinstance(out, str)
    assert "Datetime=" in out


def test_with_datetime_str_appends_and_keeps_original():
    out = _with_datetime("SYSTEM PROMPT")
    assert isinstance(out, str)
    assert out.startswith("SYSTEM PROMPT")
    assert "Datetime=" in out


def test_with_datetime_list_appends_after_cache_block():
    cached = {
        "type": "text",
        "text": "BIG CACHED PROMPT",
        "cache_control": {"type": "ephemeral"},
    }
    out = _with_datetime([cached])
    assert isinstance(out, list)
    assert len(out) == 2
    # The cached prefix block is byte-identical → prompt cache not busted.
    assert out[0] == cached
    assert out[0].get("cache_control") == {"type": "ephemeral"}
    # Datetime appended LAST, WITHOUT cache_control (sits past the breakpoint).
    assert "Datetime=" in out[1]["text"]
    assert "cache_control" not in out[1]


def test_with_datetime_does_not_mutate_caller_list():
    original = [{"type": "text", "text": "X", "cache_control": {"type": "ephemeral"}}]
    _with_datetime(original)
    assert len(original) == 1  # caller's list untouched


# ─── create_message_sync always injects (the chokepoint) ──────────────


def test_create_message_sync_injects_when_system_none():
    c, fake = _client()
    c.create_message_sync(messages=[{"role": "user", "content": "hi"}], system=None)
    sysv = fake.messages.captured["system"]
    assert sysv is not None
    assert "Datetime=" in _system_text(sysv)
    assert _dt.date.today().isoformat() in _system_text(sysv)


def test_create_message_sync_injects_when_system_str():
    c, fake = _client()
    c.create_message_sync(messages=[{"role": "user", "content": "hi"}], system="BASE PROMPT")
    sysv = fake.messages.captured["system"]
    assert isinstance(sysv, str)
    assert sysv.startswith("BASE PROMPT")
    assert "Datetime=" in sysv
    assert _dt.date.today().isoformat() in sysv


def test_create_message_sync_preserves_cache_block():
    c, fake = _client()
    cached = {"type": "text", "text": "CACHED", "cache_control": {"type": "ephemeral"}}
    c.create_message_sync(messages=[{"role": "user", "content": "hi"}], system=[cached])
    sysv = fake.messages.captured["system"]
    assert isinstance(sysv, list)
    assert sysv[0] == cached  # prefix intact → cache hits
    assert "Datetime=" in sysv[-1]["text"]
    assert "cache_control" not in sysv[-1]
    assert _dt.date.today().isoformat() in sysv[-1]["text"]


# ─── chat_compaction bypass also injects ──────────────────────────────


class _Blk:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeAsyncMessages:
    def __init__(self):
        self.captured = None

    async def create(self, **kwargs):
        self.captured = kwargs
        return type("R", (), {"content": [_Blk("summary ok")]})()


class _FakeAsyncClient:
    instances = []

    def __init__(self, *a, **k):
        self.messages = _FakeAsyncMessages()
        _FakeAsyncClient.instances.append(self)


def test_chat_compaction_injects_datetime(monkeypatch):
    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeAsyncClient)
    from zylch.services.chat_compaction import _summarize

    out = asyncio.run(_summarize("USER: ciao\n\nASSISTANT: hello"))
    assert out == "summary ok"
    cap = _FakeAsyncClient.instances[-1].messages.captured
    assert "Datetime=" in cap["system"]
    assert _dt.date.today().isoformat() in cap["system"]
