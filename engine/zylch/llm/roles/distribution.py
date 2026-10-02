"""Run-time distribution of the model table: the published record and snapshot (brief D9).

The daily job publishes the decision record `table.json` and the price and
metadata `snapshot.json` on the `model-table` data branch, under the run-time
URL every consumer reads (`gates.URL`; contract `contract/README.md`). The
engine:

- downloads both at start (`start`, called when a profile is activated) and
  every 24 hours after (`INTERVAL`, a daemon thread), each with
  ``If-None-Match`` carrying the ETag of the good copy it holds, so a file
  that did not change costs a 304 and no body;
- re-checks every download with the static gates: `gates.check_snapshot`, and
  `gates.check_table` against the requirements in force (`requirements.json`)
  and the snapshots in force (`_merged`: the first layer holding an id wins,
  as prices are read);
- caches what passes in the profile's own directory
  (`<ZYLCH_PROFILE_DIR>/model-table/`), never in a directory shared between
  profiles (a hosted tenant owns only its profile directory), with the ETag it
  came with in `etags.json`; the snapshot a newer one replaces is kept as
  `snapshot.previous.json`, so an id only the older copy knows keeps its price;
- falls back, file by file, to the last good copy, then to the build copies
  beside this module: a blocked or failed download, an HTTP error, a body that
  is not JSON or that fails a gate never replaces what is in force, and is
  logged; nothing is ever picked by name or at random.

What is in force feeds the two readers: `catalogue.set_layers(current,
previous)` puts the downloaded or last good snapshot, then the one before
it, in front of the build snapshot, and `table.set_table` puts the downloaded
or last good table in force (None: the build copy, `table.document`). `load`
applies the cached copies from disk alone, with no network, so every engine
process starts on its profile's last good copy before the first download
returns; `refresh` is one download round and applies only when a new good
copy arrived. The fetcher is a module seam (`_fetch`, or `refresh(fetch=)`),
so no test reaches the network.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from . import catalogue, gates, table

logger = logging.getLogger(__name__)

SNAPSHOT, TABLE = "snapshot.json", "table.json"
PREVIOUS = "snapshot.previous.json"
ETAGS = "etags.json"
DIRECTORY = "model-table"
INTERVAL = 24 * 60 * 60
TIMEOUT = 15.0

# A GET of `url` sent with ``If-None-Match: etag`` (None: no header) ->
# (status, body when 200, the response's ETag).
Fetch = Callable[[str, Optional[str]], "tuple[int, bytes | None, str | None]"]


def http_fetch(url: str, etag: str | None) -> tuple[int, bytes | None, str | None]:
    """The production fetcher: one GET, no redirect, no retry."""
    import httpx

    headers = {"If-None-Match": etag} if etag else {}
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
        response = client.get(url, headers=headers)
    body = response.content if response.status_code == 200 else None
    return response.status_code, body, response.headers.get("etag")


_fetch: Fetch = http_fetch
_lock = threading.RLock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_directory: str | None = None
# Where the copies in force came from, for the log and the tests.
_sources: dict = {"snapshot": "build", "table": "build"}


def cache_dir(profile_dir: str | os.PathLike | None = None) -> Path | None:
    """`<profile>/model-table/` of `profile_dir`, else of ``ZYLCH_PROFILE_DIR``;
    None without a profile (nothing is then cached, nor downloaded)."""
    directory = profile_dir or os.environ.get("ZYLCH_PROFILE_DIR")
    return Path(directory) / DIRECTORY if directory else None


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data: bytes) -> None:
    """Replace `path` with `data` atomically (a reader never sees half a file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _merged(snapshots: tuple[dict, ...]) -> dict:
    """`snapshots` then the build copy as one snapshot, the first holding an id
    winning: what a table's ranked ids are priced against, as `catalogue` reads."""
    view: dict = {"models": {}, "direct": {}}
    for doc in reversed((*snapshots, catalogue._build())):
        view["models"].update(doc["models"])
        view["direct"].update(doc["direct"])
    return view


def _good_snapshot(doc: object, where: str) -> dict | None:
    try:
        gates.check_snapshot(doc)
    except Exception as exc:  # noqa: BLE001 - untrusted input: any failure is a refusal
        logger.warning(f"[model-table] {where} snapshot refused: {exc}")
        return None
    return doc  # type: ignore[return-value]


def _good_table(doc: object, snapshots: tuple[dict, ...], where: str) -> dict | None:
    try:
        gates.check_table(doc, table.requirements(), _merged(snapshots))
    except Exception as exc:  # noqa: BLE001 - untrusted input: any failure is a refusal
        logger.warning(f"[model-table] {where} table refused: {exc}")
        return None
    return doc  # type: ignore[return-value]


def _cached(directory: Path | None) -> tuple[dict | None, dict | None, dict | None]:
    """(snapshot, previous snapshot, table) of the cache that pass the gates."""
    if directory is None:
        return None, None, None
    current = _read(directory / SNAPSHOT)
    current = _good_snapshot(current, "cached") if current is not None else None
    previous = _read(directory / PREVIOUS)
    previous = _good_snapshot(previous, "cached previous") if previous is not None else None
    front = tuple(doc for doc in (current, previous) if doc is not None)
    record = _read(directory / TABLE)
    record = _good_table(record, front, "cached") if record is not None else None
    return current, previous, record


def _apply(current: dict | None, previous: dict | None, record: dict | None, how: dict) -> None:
    """Put the copies in force; `how` says where each came from when not the build's."""
    catalogue.set_layers(*(doc for doc in (current, previous) if doc is not None))
    table.set_table(record)
    _sources.update(
        snapshot=how["snapshot"] if current is not None else "build",
        table=how["table"] if record is not None else "build",
    )
    logger.info(
        f"[model-table] in force: snapshot {_sources['snapshot']} "
        f"{(current or catalogue._build())['version']}, table {_sources['table']} "
        f"{(table.document() or {}).get('version')}"
    )


def sources() -> dict:
    """Where the snapshot and the table in force came from: `downloaded`,
    `cached` (the last good copy) or `build`."""
    return dict(_sources)


def load(profile_dir: str | os.PathLike | None = None) -> dict:
    """Put the profile's last good copies in force, from disk alone (no network)."""
    with _lock:
        current, previous, record = _cached(cache_dir(profile_dir))
        _apply(current, previous, record, {"snapshot": "cached", "table": "cached"})
        return sources()


def _download(name: str, etag: str | None, fetch: Fetch) -> tuple[bytes | None, str | None]:
    """The new body of `name` and its ETag, or (None, None): not modified or failed."""
    url = gates.URL.format(name=name)
    try:
        status, body, new_etag = fetch(url, etag)
    except Exception as exc:  # noqa: BLE001 - a failed download keeps what is in force
        logger.warning(f"[model-table] {name} download failed: {type(exc).__name__}: {exc}")
        return None, None
    if status == 304:
        logger.debug(f"[model-table] {name} not modified")
        return None, None
    if status != 200 or body is None:
        logger.warning(f"[model-table] {name} download answered HTTP {status}")
        return None, None
    return body, new_etag


def _parse(body: bytes, name: str) -> object:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        logger.warning(f"[model-table] downloaded {name} is not JSON: {exc}")
        return None


def refresh(profile_dir: str | os.PathLike | None = None, *, fetch: Fetch | None = None) -> dict:
    """One download round of both files; a good new copy is cached and put in force."""
    directory = cache_dir(profile_dir)
    if directory is None:
        logger.debug("[model-table] no profile directory: nothing downloaded")
        return sources()
    fetch = fetch or _fetch
    with _lock:
        current, previous, record = _cached(directory)
        etags = _read(directory / ETAGS) or {}
        how = {"snapshot": "cached", "table": "cached"}
        body, etag = _download(SNAPSHOT, etags.get(SNAPSHOT) if current else None, fetch)
        doc = _good_snapshot(_parse(body, SNAPSHOT), "downloaded") if body else None
        if doc is not None:
            if current is not None and current["version"] != doc["version"]:
                os.replace(directory / SNAPSHOT, directory / PREVIOUS)
                previous = current
            _write(directory / SNAPSHOT, body)
            current, etags[SNAPSHOT], how["snapshot"] = doc, etag, "downloaded"
        front = tuple(doc for doc in (current, previous) if doc is not None)
        if how["snapshot"] == "downloaded" and record is not None:
            # A new snapshot must still price the cached table, else the build copy's.
            record = _good_table(record, front, "cached")
        body, etag = _download(TABLE, etags.get(TABLE) if record else None, fetch)
        doc = _good_table(_parse(body, TABLE), front, "downloaded") if body else None
        if doc is not None:
            _write(directory / TABLE, body)
            record, etags[TABLE], how["table"] = doc, etag, "downloaded"
        if "downloaded" in how.values():
            _write(directory / ETAGS, json.dumps(etags, sort_keys=True).encode("utf-8"))
            _apply(current, previous, record, how)
        return sources()


def _loop() -> None:
    while not _stop.is_set():
        try:
            refresh(_directory)
        except Exception as exc:  # noqa: BLE001 - the loop outlives any one round
            logger.warning(f"[model-table] refresh failed: {type(exc).__name__}: {exc}")
        _stop.wait(INTERVAL)


def start(profile_dir: str | os.PathLike | None = None) -> None:
    """At engine start: the last good copies at once (no network), then a download
    in the background now and every `INTERVAL` seconds (one thread per process)."""
    global _thread, _directory
    load(profile_dir)
    with _lock:
        _directory = str(profile_dir) if profile_dir else os.environ.get("ZYLCH_PROFILE_DIR")
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="model-table", daemon=True)
        _thread.start()
