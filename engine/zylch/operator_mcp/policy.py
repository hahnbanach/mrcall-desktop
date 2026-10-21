from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from zylch.services import task_assignment_identity as identity
from zylch.services import task_assignment_trust as trust

from .issuer import ProfilePolicy
from .read_port import ProfileBinding


class PolicyError(ValueError):
    pass


_PROFILE_KEYS = frozenset(
    {
        "profile_uid",
        "email",
        "company_ref",
        "resource",
        "mailbox_ids",
        "service_client_id",
        "service_secret",
    }
)
_UID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _refuse():
    raise PolicyError("Operator policy unavailable")


def _text(value, maximum=256):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        _refuse()
    return value


def _origin(value):
    _text(value, 2048)
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or parsed.netloc != parsed.netloc.lower()
            or "%" in parsed.netloc
            or any(c.isspace() for c in value)
            or "\\" in value
        ):
            _refuse()
        if value != "https://" + parsed.netloc:
            _refuse()
        return value
    except ValueError:
        _refuse()


def _profile(row, issuer):
    uid = _text(row["profile_uid"], 128)
    if not _UID.fullmatch(uid):
        _refuse()
    email = _text(row["email"])
    if email != email.strip().lower() or not re.fullmatch(r"[^\s@]+@[^\s@]+", email):
        _refuse()
    if not _UID.fullmatch(_text(row["company_ref"], 128)):
        _refuse()
    if row["resource"] != issuer + "/operator/" + uid + "/mcp":
        _refuse()
    mailboxes = row["mailbox_ids"]
    if not isinstance(mailboxes, list) or len(mailboxes) != 1:
        _refuse()
    _text(mailboxes[0])
    _text(row["service_client_id"])
    secret = _text(row["service_secret"], 4096)
    if len(secret) < 16 or secret != secret.strip():
        _refuse()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _refuse()
        result[key] = value
    return result


def _read(path):
    try:
        path = Path(path)
        raw = trust.protected_read(path)
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o026
            or info.st_nlink != 1
        ):
            _refuse()
        value = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=lambda value: _refuse()
        )
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or value["version"] != 1
        ):
            _refuse()
        return value
    except Exception:
        raise PolicyError("Operator policy unavailable") from None


def load_broker_config(path) -> dict:
    try:
        value = _read(path)
        if set(value) != {"version", "issuer", "firebase_project", "native_callbacks", "profiles"}:
            _refuse()
        issuer = _origin(value["issuer"])
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,62}", _text(value["firebase_project"], 63)):
            _refuse()
        callbacks = value["native_callbacks"]
        if not isinstance(callbacks, list) or not 1 <= len(callbacks) <= 16:
            _refuse()
        seen_callbacks = set()
        for row in callbacks:
            if not isinstance(row, dict) or set(row) != {"host", "path"}:
                _refuse()
            host, path = row["host"], _text(row["path"], 256)
            if (
                host not in {"localhost", "127.0.0.1", "::1"}
                or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]*", path)
                or (host, path) in seen_callbacks
            ):
                _refuse()
            seen_callbacks.add((host, path))
        profiles = value["profiles"]
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= 256:
            _refuse()
        seen = {key: set() for key in ("profile_uid", "resource", "email", "service_client_id")}
        for row in profiles:
            if (
                not isinstance(row, dict)
                or set(row) != _PROFILE_KEYS | {"enabled"}
                or type(row["enabled"]) is not bool
            ):
                _refuse()
            _profile(row, issuer)
            for key, values in seen.items():
                if row[key] in values:
                    _refuse()
                values.add(row[key])
        return value
    except Exception:
        raise PolicyError("Operator policy unavailable") from None


def load_profile_config(path) -> dict:
    try:
        value = _read(path)
        if set(value) != _PROFILE_KEYS | {"version", "issuer", "socket_path"}:
            _refuse()
        _profile(value, _origin(value["issuer"]))
        if value["socket_path"] != "/run/mrcalld/" + value["profile_uid"] + "/operator-mcp.sock":
            _refuse()
        return value
    except Exception:
        raise PolicyError("Operator policy unavailable") from None


def broker_policy(path):
    def resolve(resource):
        try:
            config = load_broker_config(path)
            row = next((row for row in config["profiles"] if row["resource"] == resource), None)
            if row is None or row["enabled"] is not True:
                return None
            current = trust.load(row["company_ref"])
            trust.member(current, row["profile_uid"], row["email"])
            return ProfilePolicy(
                profile_uid=row["profile_uid"],
                email=row["email"],
                company_ref=row["company_ref"],
                resource=row["resource"],
                mailbox_ids=frozenset(row["mailbox_ids"]),
                service_client_id=row["service_client_id"],
                service_secret=row["service_secret"],
            )
        except Exception:
            return None

    return resolve


def profile_binding(config) -> ProfileBinding:
    try:
        from zylch.cli.utils import get_owner_id
        from zylch.email import mailboxes
        from zylch.services import project_store

        if set(config) != _PROFILE_KEYS | {"version", "issuer", "socket_path"}:
            _refuse()
        _profile(config, _origin(config["issuer"]))
        if type(config["version"]) is not int or config["version"] != 1:
            _refuse()
        if config["socket_path"] != "/run/mrcalld/" + config["profile_uid"] + "/operator-mcp.sock":
            _refuse()
        before = identity.binding()
        uid, email = config["profile_uid"], config["email"]
        if (
            before[0] != uid
            or os.environ.get("OWNER_ID") != uid
            or os.environ.get("EMAIL_ADDRESS") != email
            or get_owner_id() != email
        ):
            _refuse()
        with project_store.connection(expected_space=config["company_ref"]) as (_, space):
            if space != config["company_ref"]:
                _refuse()
            mailbox = mailboxes.primary(email)
            if (
                mailbox is None
                or mailbox.id != config["mailbox_ids"][0]
                or mailbox.owner_id != email
                or mailbox.address != email
                or mailbox.is_primary is not True
                or mailbox.removed_at is not None
                or (
                    mailbox.preset is not None
                    and (
                        not isinstance(mailbox.preset, str)
                        or mailbox.preset
                        not in {
                            item["id"]
                            for item in mailboxes.presets()
                            if "pec" not in item["id"].lower()
                        }
                    )
                )
                or any(
                    "pec" in str(getattr(mailbox, key, "") or "").lower()
                    for key in ("imap_host", "smtp_host")
                )
                or email.rsplit("@", 1)[-1] == "pec.net"
            ):
                _refuse()
            current = trust.load(space)
            trust.member(current, uid, email)
        if identity.binding() != before:
            _refuse()
        return ProfileBinding(uid, email, space, frozenset(config["mailbox_ids"]))
    except Exception:
        raise PolicyError("Operator profile binding unavailable") from None
