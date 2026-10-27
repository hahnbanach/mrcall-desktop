"""Pure immutable receipt matching; imports no identity, database or service code."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import heapq
import json


@dataclass(frozen=True)
class EvidenceMatch:
    path: tuple
    digest: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class Snapshot:
    rows: tuple[tuple, ...]
    lengths: tuple[int, ...]
    patterns: tuple[tuple[str, str], ...] = ()


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: object, *, text: bool = False) -> str:
    payload = value.strip() if text else canonical(value)
    return hashlib.sha256(("text:" if text else "json:").encode() + payload.encode()).hexdigest()


def values(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError, RecursionError):
            return
        if isinstance(parsed, (dict, list)):
            yield from values(parsed)
    elif isinstance(value, (dict, list)):
        for options in (
            {"ensure_ascii": False, "sort_keys": True, "separators": (",", ":")},
            {"ensure_ascii": False},
            {"ensure_ascii": True},
        ):
            yield json.dumps(value, **options)
        for child in value.values() if isinstance(value, dict) else value:
            yield from values(child)
    elif isinstance(value, bytes):
        yield base64.b64encode(value).decode("ascii")
        try:
            decoded = value.decode("utf-8")
        except UnicodeDecodeError:
            return
        yield from values(decoded)


def recover(
    rows: Sequence[tuple], uid: str, sources: Sequence[object], maximum: int = 8 * 1024 * 1024
) -> tuple[tuple[str, str], ...]:
    wanted = {row[1]: row[5] for row in rows if row[0] == uid and row[5]}
    recovered: dict[str, str] = {}
    used = 0
    for source in sources:
        try:
            for candidate in values(source):
                candidate = candidate.strip()
                key = digest(candidate, text=True)
                if key in recovered or wanted.get(key) != len(candidate):
                    continue
                cost = len(candidate.encode()) * 4 + len(key) + 256
                if len(recovered) >= 4096 or used + cost > maximum:
                    continue
                recovered[key] = candidate
                used += cost
        except (ValueError, TypeError, RecursionError, UnicodeError):
            continue
    return tuple(recovered.items())


def _windows(text: str, pattern: str, key: str, length: int) -> Iterator[tuple[int, str, int, int]]:
    if len(pattern) > length:
        return
    position = text.find(pattern)
    while position >= 0:
        end = position + len(pattern)
        left = position
        while left > max(0, end - length) and text[left - 1].isspace():
            left -= 1
        right = end
        while right < min(len(text), position + length) and text[right].isspace():
            right += 1
        for offset in range(max(left, end - length), min(position, right - length) + 1):
            yield offset, key, position, end
        position = text.find(pattern, position + 1)


def windows(
    text: str,
    lengths: Sequence[int] | set[int],
    known: set[str],
    patterns: Mapping[str, str],
    digest: Callable[..., str],
) -> Iterator[tuple[int, str, int, int]]:
    active = [(key, pattern) for key, pattern in patterns.items() if pattern in text]
    fallback = known.difference(patterns)

    def exhaustive(length: int) -> Iterator[tuple[int, str, int, int]]:
        for offset in range(len(text) - length + 1):
            window = text[offset : offset + length]
            key = digest(window, text=True)
            if key in fallback:
                yield offset, key, offset + len(window) - len(window.lstrip()), offset + len(
                    window.rstrip()
                )

    for length in lengths:
        if length >= len(text):
            continue
        streams = [_windows(text, pattern, key, length) for key, pattern in active]
        if fallback:
            streams.append(exhaustive(length))
        yield from heapq.merge(*streams)


def matches(
    value: object, snapshot: Snapshot, hash_value: Callable[..., str] = digest
) -> Iterator[EvidenceMatch]:
    known = {row[1] for row in snapshot.rows}
    if not known:
        return
    text_known = {row[1] for row in snapshot.rows if row[5]}
    patterns = dict(snapshot.patterns)

    def candidates(item: object, path: tuple) -> Iterator[EvidenceMatch]:
        if isinstance(item, (dict, list)):
            key = hash_value(item) if item else None
            if key in known:
                yield EvidenceMatch(path, key)
            children = item.items() if isinstance(item, dict) else enumerate(item)
            for part, child in children:
                yield from candidates(child, (*path, part))
        elif isinstance(item, str):
            key = hash_value(item, text=True)
            if key in known:
                start = len(item) - len(item.lstrip())
                yield EvidenceMatch(path, key, start, len(item.rstrip()))
            try:
                parsed = json.loads(item)
            except (ValueError, TypeError):
                return
            if isinstance(parsed, (list, dict)):
                yield from candidates(parsed, (*path, "$json"))

    def substrings(item: object, path: tuple) -> Iterator[EvidenceMatch]:
        if isinstance(item, str):
            text = item.strip()
            leading = len(item) - len(item.lstrip())
            for _, key, start, end in windows(
                text, snapshot.lengths, text_known, patterns, hash_value
            ):
                yield EvidenceMatch(path, key, leading + start, leading + end)
        elif isinstance(item, (dict, list)):
            children = item.items() if isinstance(item, dict) else enumerate(item)
            for part, child in children:
                yield from substrings(child, (*path, part))

    yield from candidates(value, ())
    yield from substrings(value, ())
