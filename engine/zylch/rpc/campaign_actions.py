"""RPC handlers for outreach campaigns (`campaign.*`).

Campaigns are the durable state of operator-driven outreach (mrcall-cs
or any support session): one row per campaign, one row per recipient
with verdict / language / dossier / draft / send-state. Stored in the
engine DB so no session loses another session's work.

Kept separate from `rpc/methods.py` per the 500-line module guideline.
All methods are owner-scoped; none of them SENDS anything — sending
stays behind the existing approval-gated paths.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]

CONTACT_STATES = {"drafted", "approved", "sent", "replied", "bounced", "skipped"}

# Fields a client may set on add/update. Everything else is server-side.
_CONTACT_FIELDS = {
    "email",
    "uid",
    "stratum",
    "verdict",
    "language",
    "dossier",
    "draft_subject",
    "draft_body",
    "state",
    "message_id",
}


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def campaign_create(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """campaign.create(name, brief?) -> campaign dict."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Campaign

    name = (params.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    brief = params.get("brief") or ""

    owner_id = _owner_id()
    with get_session() as session:
        row = Campaign(owner_id=owner_id, name=name, brief=brief)
        session.add(row)
        session.flush()
        out = row.to_dict()
    logger.info(f"[rpc:campaign.create] name={name!r} id={out['id']}")
    return out


async def campaign_list(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """campaign.list() -> list of campaigns with contact/state counts."""
    from sqlalchemy import func

    from zylch.storage.database import get_session
    from zylch.storage.models import Campaign, CampaignContact

    owner_id = _owner_id()
    with get_session() as session:
        camps = (
            session.query(Campaign)
            .filter(Campaign.owner_id == owner_id)
            .order_by(Campaign.created_at.desc())
            .all()
        )
        out = []
        for c in camps:
            counts = dict(
                session.query(CampaignContact.state, func.count())
                .filter(CampaignContact.campaign_id == c.id)
                .group_by(CampaignContact.state)
                .all()
            )
            d = c.to_dict()
            d["contacts_by_state"] = counts
            out.append(d)
    return out


async def campaign_add_contact(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """campaign.add_contact(campaign_id, email, …fields) -> contact dict.

    Idempotent on (campaign_id, email): re-adding an existing contact
    updates the provided fields instead of failing on the unique
    constraint, so a re-run of a backfill/pipeline never duplicates.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Campaign, CampaignContact

    campaign_id = params.get("campaign_id")
    email = (params.get("email") or "").strip().lower()
    if not campaign_id:
        raise ValueError("campaign_id is required")
    if not email:
        raise ValueError("email is required")
    state = params.get("state") or "drafted"
    if state not in CONTACT_STATES:
        raise ValueError(f"state must be one of {sorted(CONTACT_STATES)}")

    fields = {k: params[k] for k in _CONTACT_FIELDS if k in params}
    fields["email"] = email
    fields["state"] = state

    owner_id = _owner_id()
    with get_session() as session:
        camp = (
            session.query(Campaign)
            .filter(Campaign.id == campaign_id, Campaign.owner_id == owner_id)
            .one_or_none()
        )
        if camp is None:
            raise ValueError("campaign not found")
        row = (
            session.query(CampaignContact)
            .filter(
                CampaignContact.campaign_id == campaign_id,
                CampaignContact.email == email,
            )
            .one_or_none()
        )
        if row is None:
            row = CampaignContact(owner_id=owner_id, campaign_id=campaign_id, **fields)
            session.add(row)
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        session.flush()
        out = row.to_dict()
    logger.debug(f"[rpc:campaign.add_contact] campaign={campaign_id} email={email} state={state}")
    return out


async def campaign_contacts(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """campaign.contacts(campaign_id, state?) -> list of contact dicts."""
    from zylch.storage.database import get_session
    from zylch.storage.models import CampaignContact

    campaign_id = params.get("campaign_id")
    if not campaign_id:
        raise ValueError("campaign_id is required")
    state = params.get("state")

    owner_id = _owner_id()
    with get_session() as session:
        q = session.query(CampaignContact).filter(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.owner_id == owner_id,
        )
        if state:
            q = q.filter(CampaignContact.state == state)
        rows = q.order_by(CampaignContact.created_at.asc()).all()
        return [r.to_dict() for r in rows]


async def campaign_update_contact(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """campaign.update_contact(contact_id, …fields) -> {ok, contact}.

    `state=sent` stamps `sent_at` server-side.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import CampaignContact

    contact_id = params.get("contact_id")
    if not contact_id:
        raise ValueError("contact_id is required")
    state = params.get("state")
    if state is not None and state not in CONTACT_STATES:
        raise ValueError(f"state must be one of {sorted(CONTACT_STATES)}")

    fields = {k: params[k] for k in _CONTACT_FIELDS if k in params and k != "email"}

    owner_id = _owner_id()
    with get_session() as session:
        row = (
            session.query(CampaignContact)
            .filter(
                CampaignContact.id == contact_id,
                CampaignContact.owner_id == owner_id,
            )
            .one_or_none()
        )
        if row is None:
            return {"ok": False, "error": "contact not found"}
        for k, v in fields.items():
            setattr(row, k, v)
        if state == "sent" and row.sent_at is None:
            row.sent_at = datetime.now(timezone.utc)
        session.flush()
        out = row.to_dict()
    logger.debug(f"[rpc:campaign.update_contact] id={contact_id} state={state}")
    return {"ok": True, "contact": out}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "campaign.create": campaign_create,
    "campaign.list": campaign_list,
    "campaign.add_contact": campaign_add_contact,
    "campaign.contacts": campaign_contacts,
    "campaign.update_contact": campaign_update_contact,
}
