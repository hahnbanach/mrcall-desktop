"""Opt-in operator rehearsal composition for the existing WebSocket host."""

import json
import logging
import os
import stat
import time
from pathlib import Path

from zylch.assistant.installation import InstallationSpec, _object
from zylch.assistant.procedure import ProcedureArtifact
from zylch.services.capability_contract import CapabilityBinding, ContactGrant
from zylch.services.order_existence import _mailbox
from zylch.services.procedure_email import EmailSelection, source_revision
from zylch.services.procedure_installation import PilotProcedureInstallation
from zylch.services.scoped_capabilities import current_profile_scope

logger = logging.getLogger(__name__)
_FIELDS = frozenset(
    {
        "version",
        "installation_path",
        "installation_revision",
        "procedure_path",
        "procedure_revision",
        "profile_uid",
        "company_key",
        "service_uid",
        "contact_ref",
        "contact_email",
        "owner_email",
        "issued_at_ms",
        "expires_at_ms",
        "clone_dir",
    }
)


def _read(path, limit, *, private=False):
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError("pilot path must be absolute")
    with open(path, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or (
            private and (info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o077)
        ):
            raise ValueError("pilot configuration must be private")
        raw = stream.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError("pilot file exceeds bounds")
    return raw


def _provider(config):
    """Resolve the selected clone once; renewable tokens are resolved per read.

    Startup runs before connections/tasks. The explicit manifest selects company
    configuration; credentials use the existing kernel environment layers under
    the actual service user's HOME. No clone owner session is read or installed.
    """
    from cs.config import load
    from cs.crm.shopify import _access_token
    from cs.manifest import load_manifest
    from cs.shopify_client import ShopifyReadConnection, fetch_customers

    directory = Path(config["clone_dir"])
    if not directory.is_absolute() or not (directory / "manifest.toml").is_file():
        raise ValueError("pilot clone manifest unavailable")
    manifest_path = directory / "manifest.toml"
    declared = load_manifest(manifest_path)
    if (
        declared.engine.owner_uid != config["profile_uid"]
        or _mailbox(declared.operator.email_address) != config["owner_email"]
    ):
        raise ValueError("pilot clone identity mismatch")
    settings = load(manifest_path=manifest_path)
    if (
        settings.engine_owner_uid != config["profile_uid"]
        or _mailbox(settings.email_address) != config["owner_email"]
    ):
        raise ValueError("pilot clone identity mismatch")
    if not settings.shopify_store_domain or not (
        settings.shopify_admin_token or (settings.shopify_client_id and settings.shopify_secret)
    ):
        raise ValueError("pilot provider credentials unavailable")

    def read(email):
        connection = ShopifyReadConnection(
            store_domain=settings.shopify_store_domain,
            api_version=settings.shopify_api_version,
            access_token=_access_token(settings),
        )
        return fetch_customers(connection, email, timeout=2)

    return read


class LivePilot:
    def __init__(self, config, installation):
        self.config = config
        self.installation = installation

    async def draft(self, source_id, claims):
        """Use connection-verified owner claims, never process-global auth state."""
        from zylch.services.chat_service import ChatService
        from zylch.storage import Storage

        def authorized():
            self.installation.service.check_scope()
            if (
                claims.get("sub") != self.config["profile_uid"]
                or type(claims.get("exp")) is not int
                or claims["exp"] * 1000 <= time.time_ns() // 1_000_000
            ):
                raise PermissionError("pilot owner authentication expired")

        authorized()
        if not isinstance(source_id, str) or not 0 < len(source_id) <= 256:
            raise ValueError("invalid source selection")
        storage = Storage.get_instance()
        owner = self.config["profile_uid"]
        source = storage.get_email_by_supabase_id(owner, source_id)
        if (
            not source
            or source.get("owner_id") != owner
            or source.get("id") != source_id
            or _mailbox(source.get("from_email")) != self.config["contact_email"]
            or _mailbox(source.get("to_email")) != self.config["owner_email"]
        ):
            raise PermissionError("pilot inbound source denied")
        selection = EmailSelection(
            source_id,
            source_revision(source),
            self.config["contact_email"],
            self.config["contact_ref"],
        )
        with self.installation.prepare_email(
            selection, storage, owner, check_authority=authorized
        ) as prepared:
            # Recheck the connection's auth at every source/output check, including
            # after pending provider/model work. Never grant the owner grace period.
            result = await ChatService(pilot_email_route=prepared.route).process_message(
                "", owner, context={"email_id": source_id}
            )
            authorized()
            return result

    def close(self):
        self.installation.close()


def load_live_pilot():
    """Absent configuration opts out; any enabled configuration failure is fatal."""
    path = os.environ.get("MRCALL_PILOT_CONFIG")
    if path is None:
        return None
    try:
        config = json.loads(_read(path, 8192, private=True), object_pairs_hook=_object)
        if (
            not isinstance(config, dict)
            or set(config) != _FIELDS
            or type(config["version"]) is not int
            or config["version"] != 1
            or any(type(config[k]) is not int for k in ("issued_at_ms", "expires_at_ms"))
            or not 0 < config["expires_at_ms"] - config["issued_at_ms"] <= 86_400_000
            or any(
                not isinstance(config[k], str) or not config[k]
                for k in _FIELDS - {"version", "issued_at_ms", "expires_at_ms"}
            )
            or any(_mailbox(config[k]) != config[k] for k in ("owner_email", "contact_email"))
            or config["owner_email"] == config["contact_email"]
        ):
            raise ValueError("invalid pilot configuration")

        def scope():
            now = time.time_ns() // 1_000_000
            if not config["issued_at_ms"] <= now < config["expires_at_ms"]:
                raise PermissionError("pilot activation expired")
            if _mailbox(os.environ.get("EMAIL_ADDRESS")) != config["owner_email"]:
                raise PermissionError("pilot mailbox changed")
            return current_profile_scope()

        artifact = ProcedureArtifact.parse(
            _read(config["procedure_path"], 16384), config["procedure_revision"]
        )
        spec = InstallationSpec.parse(
            _read(config["installation_path"], 4096),
            config["installation_revision"],
            artifact.revision,
        )
        binding = CapabilityBinding(
            spec.business_id,
            config["profile_uid"],
            config["service_uid"],
            config["company_key"],
            artifact.revision,
            (ContactGrant(config["contact_ref"], config["contact_email"]),),
        )
        if scope() != (binding.profile_uid, binding.company_key):
            raise PermissionError("pilot profile scope mismatch")
        from zylch.storage.database import get_session

        installation = PilotProcedureInstallation(
            spec,
            artifact,
            binding,
            connection_ref=spec.connection_ref,
            authority_ref=spec.authority_ref,
            read_customers=_provider(config),
            session_factory=get_session,
            profile_scope=scope,
            allowed_operations=frozenset({"order.exists"}),
        )
        logger.debug("[live pilot] startup -> installed")
        return LivePilot(config, installation)
    except Exception:  # noqa: BLE001 -- dependency errors can contain private configuration
        # Neither private configuration nor dependency diagnostics enter logs.
        raise ValueError("live pilot configuration unavailable or invalid") from None
