"""The command templates are encoded once, not on every message.

`match()` used to embed all 221 constant command templates one at a
time, every call, and cache nothing — 221 ONNX forward passes to decide
whether one sentence was a slash command. The templates never change, so
they are encoded once per process in a single batch and matching is one
encode of the user's message plus a dot product.

The embedding engine is faked here because it IS the outbound boundary
(an ONNX model load); everything else — `COMMAND_PATTERNS`, the scoring,
the parameter extraction, the formatters — is the real code.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from zylch.services.command_handlers import COMMAND_PATTERNS
from zylch.services.command_matcher import SemanticCommandMatcher

TEMPLATE_COUNT = sum(len(templates) for templates in COMMAND_PATTERNS.values())


class _RecordingEngine:
    """Deterministic embeddings, with a log of every encode call."""

    def __init__(self):
        self.calls: list = []

    def _vector(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
        return rng.standard_normal(384).astype(np.float32)

    def encode(self, text):
        if isinstance(text, str):
            self.calls.append(("single", text))
            return self._vector(text)
        self.calls.append(("batch", list(text)))
        return np.stack([self._vector(t) for t in text])

    def similarity(self, a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    @property
    def batches(self):
        return [call for call in self.calls if call[0] == "batch"]

    @property
    def singles(self):
        return [call for call in self.calls if call[0] == "single"]


@pytest.fixture
def engine(monkeypatch):
    import zylch.memory as memory_pkg

    recording = _RecordingEngine()
    monkeypatch.setattr(memory_pkg, "get_shared_engine", lambda _config: recording)
    SemanticCommandMatcher.reset_template_index()
    yield recording
    SemanticCommandMatcher.reset_template_index()


def test_matching_twice_encodes_the_templates_once(engine):
    matcher = SemanticCommandMatcher()

    matcher.match("sync my mailbox please")
    matcher.match("show me what is in the archive")

    assert len(engine.batches) == 1
    assert len(engine.batches[0][1]) == TEMPLATE_COUNT
    # One encode per user message, and nothing else.
    assert len(engine.singles) == 2


def test_a_second_matcher_instance_reuses_the_encoded_templates(engine):
    """A `ChatService` is built per chat turn; its matcher must be free."""
    SemanticCommandMatcher().match("sync my mailbox please")
    SemanticCommandMatcher().match("sync my mailbox please")

    assert len(engine.batches) == 1


def test_the_template_parameters_are_stripped_before_encoding(engine):
    SemanticCommandMatcher().match("anything at all")

    encoded = engine.batches[0][1]
    assert not any("{" in text for text in encoded)


def test_an_exact_template_still_resolves_to_its_command(engine):
    """Caching must not change what matches — only when it is computed."""
    matcher = SemanticCommandMatcher()

    assert matcher.match("synchronize") == "/sync"


def test_an_unrelated_message_still_matches_nothing(engine):
    matcher = SemanticCommandMatcher()

    assert matcher.match("the quarterly numbers looked odd to me yesterday") is None
