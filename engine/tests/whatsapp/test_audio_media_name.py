"""Voice-note files cannot be named outside the profile's ``wa_media`` folder.

``WhatsAppSyncService._download_audio`` names the file after the WhatsApp
message id, which the sender's client chooses. A plain-token id
(``[A-Za-z0-9_-]{1,128}``, as real hex-like ids are) is the stem unchanged;
any other id becomes ``wa_`` + 32 hex digits of its SHA-256, and the final
path is confined to ``wa_media``. Threat model and criterion 2 of
docs/briefs/2026-09-29-toward-sandbox.md: one crafted message must not write
into a sibling profile, e.g. over its pending voice note.
"""

import os
import re
import sys
from pathlib import Path

import pytest

# neonize ships its proto bindings as a non-namespaced ``Neonize_pb2`` module
# importable only from inside ``neonize/proto`` (same setup as test_sync.py).
import neonize  # noqa: E402

_NEONIZE_PROTO = Path(neonize.__file__).resolve().parent / "proto"
if _NEONIZE_PROTO.exists() and str(_NEONIZE_PROTO) not in sys.path:
    sys.path.insert(0, str(_NEONIZE_PROTO))

AUDIO = b"OggS\x00\x02fake-opus-bytes"
VICTIM_BYTES = b"sibling pending voice note"
HASHED_NAME = re.compile(r"wa_[0-9a-f]{32}\.ogg")
UNSAFE_IDS = {
    "dotdot": "../../x",
    "absolute": "/abs/path",
    "slash": "a/b",
    "backslash-dotdot": "..\\x",
    "empty": "",
    "500-chars": "A" * 500,
    "129-chars": "B" * 129,
    "trailing-newline": "3EB0ABC\n",
}


class _FakeWAClient:
    """Stands in for WhatsAppClient: ``download_media`` returns fixed bytes."""

    def __init__(self, data: bytes = AUDIO):
        self.data = data

    def download_media(self, message):
        return self.data


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    """A tenant profile, and a sibling profile holding a pending voice note.

    The service runs as the tenant (``ZYLCH_PROFILE_DIR``); HOME and
    ZYLCH_HOME also point into tmp_path. Returns (tmp_path, the tenant's
    resolved wa_media path, the sibling's voice-note file).
    """
    tenant = tmp_path / "profiles" / "tenant"
    sibling_media = tmp_path / "profiles" / "sibling" / "wa_media"
    tenant.mkdir(parents=True)
    sibling_media.mkdir(parents=True)
    victim = sibling_media / "3EB0VICTIM.ogg"
    victim.write_bytes(VICTIM_BYTES)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZYLCH_HOME", str(tmp_path / "home" / ".zylch"))
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tenant))
    return tmp_path, Path(os.path.realpath(tenant)) / "wa_media", victim


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB under tmp_path/db. Disposes the engine on teardown."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_dir / "wa.db"))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_dir
    db_mod.dispose_engine()


def _service(data: bytes = AUDIO):
    from zylch.whatsapp.sync import WhatsAppSyncService

    svc = WhatsAppSyncService(storage=None, owner_id="owner@example.com")
    svc.wa_client = _FakeWAClient(data)
    return svc


def _download(msg_id: str, data: bytes = AUDIO):
    return _service(data)._download_audio(msg_id, unwrapped=object())


def _outside(tmp_path: Path, media: Path) -> dict[str, bytes]:
    """Every file under tmp_path outside ``media`` (the test database
    directory excepted), with its content: comparing two snapshots shows any
    file created, changed or removed outside ``wa_media``."""
    skip = Path(os.path.realpath(tmp_path / "db"))
    files = {}
    for dirpath, _, names in os.walk(tmp_path):
        for name in names:
            real = Path(os.path.realpath(os.path.join(dirpath, name)))
            if real.parent != media and skip not in real.parents:
                files[str(real)] = real.read_bytes()
    return files


@pytest.mark.parametrize(
    "msg_id",
    [
        "3EB0C767D26A1B2C3D4E",
        "A1B2C3D4E5F60718293A4B5C6D7E8F90",
        "3EB0_x-9",
        "F" * 128,
    ],
)
def test_plain_id_is_the_file_stem(profiles, msg_id):
    tmp_path, media, _ = profiles
    before = _outside(tmp_path, media)

    path = _download(msg_id)

    assert path == str(media / f"{msg_id}.ogg")
    assert Path(path).read_bytes() == AUDIO
    assert _outside(tmp_path, media) == before


@pytest.mark.parametrize("msg_id", list(UNSAFE_IDS.values()), ids=list(UNSAFE_IDS))
def test_unsafe_id_gets_a_hashed_stem_inside_wa_media(profiles, msg_id):
    tmp_path, media, _ = profiles
    before = _outside(tmp_path, media)

    path = _download(msg_id)

    assert path is not None
    assert Path(path).parent == media
    assert HASHED_NAME.fullmatch(Path(path).name)
    assert Path(path).read_bytes() == AUDIO
    assert _outside(tmp_path, media) == before


def test_distinct_unsafe_ids_do_not_collide(profiles):
    tmp_path, media, _ = profiles
    before = _outside(tmp_path, media)
    # "a/b", "a\\b" and the plain id "b" share a basename; hashing keeps
    # them apart.
    ids = list(UNSAFE_IDS.values()) + ["a\\b", "../x", "b"]

    paths = [_download(msg_id, data=f"voice {i}".encode()) for i, msg_id in enumerate(ids)]

    assert len(set(paths)) == len(ids)
    for i, path in enumerate(paths):
        assert Path(path).parent == media
        assert Path(path).read_bytes() == f"voice {i}".encode()
    assert _outside(tmp_path, media) == before
    # The same id maps to the same file: a re-delivered message reuses it.
    assert _download(ids[0]) == paths[0]


@pytest.mark.parametrize("absolute", [False, True])
def test_crafted_id_cannot_overwrite_a_sibling_voice_note(profiles, absolute):
    tmp_path, media, victim = profiles
    before = _outside(tmp_path, media)
    msg_id = str(victim.with_suffix("")) if absolute else "../../sibling/wa_media/3EB0VICTIM"

    path = _download(msg_id, data=b"attacker bytes")

    assert Path(path).parent == media
    assert victim.read_bytes() == VICTIM_BYTES
    assert _outside(tmp_path, media) == before


def test_voice_event_with_crafted_id_stores_a_confined_media_path(profiles, fresh_db):
    """End to end: the protocol id of a live voice-note event reaches the
    download unmodified, and the stored row points inside ``wa_media``."""
    import Neonize_pb2 as N

    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    tmp_path, media, victim = profiles
    before = _outside(tmp_path, media)
    msg_id = "../../sibling/wa_media/3EB0VICTIM"
    ev = N.Message()
    ev.Info.ID = msg_id
    ev.Info.Pushname = "Sender"
    ev.Info.Timestamp = 1_700_000_000
    src = ev.Info.MessageSource
    src.Chat.User = src.Sender.User = "393281234567"
    src.Chat.Server = src.Sender.Server = "s.whatsapp.net"
    ev.Message.audioMessage.PTT = True

    assert _service(b"attacker bytes")._store_message_from_event(ev) is True

    with get_session() as session:
        row = session.query(WhatsAppMessage).filter_by(message_id=msg_id).one()
        media_type, media_path = row.media_type, row.media_path
    assert media_type == "voice"
    assert Path(media_path).parent == media
    assert HASHED_NAME.fullmatch(Path(media_path).name)
    assert Path(media_path).read_bytes() == b"attacker bytes"
    assert victim.read_bytes() == VICTIM_BYTES
    assert _outside(tmp_path, media) == before
