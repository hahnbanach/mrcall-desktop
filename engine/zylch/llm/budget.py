"""Atomic per-owner LLM cost admission in the existing profile SQLite store."""

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, inspect, select

from .budget_pricing import BudgetError, micro_usd, request_bound, usage_cost


@dataclass(frozen=True)
class Reservation:
    id: str
    owner_id: str
    model: str
    transport: str
    reserved_micro_usd: int
    call_site: str


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def _budget():
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR")
    if profile_dir:
        from io import StringIO
        from pathlib import Path

        from dotenv import dotenv_values
        from dotenv.parser import parse_stream

        try:
            content = (Path(profile_dir) / ".env").read_text(encoding="utf-8")
            if any(binding.error for binding in parse_stream(StringIO(content))):
                raise BudgetError("AI paused: saved profile settings are malformed.")
            values = dotenv_values(stream=StringIO(content), interpolate=False)
        except (OSError, UnicodeError):
            raise BudgetError("AI paused: the saved budget setting is unavailable.") from None
        raw = values.get("LLM_DAILY_BUDGET_USD", "")
    else:
        raw = os.environ.get("LLM_DAILY_BUDGET_USD", "")
    return micro_usd(str(raw or "").strip() or "10")


@contextmanager
def _transaction():
    from zylch.storage.database import get_engine

    try:
        engine = get_engine()
        with engine.connect() as conn:
            if not inspect(conn).has_table("llm_usage") or not inspect(conn).has_table(
                "llm_reservations"
            ):
                raise BudgetError(
                    "AI paused: budget ledger is unavailable; initialize the engine database."
                )
            conn.commit()
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
    except BudgetError:
        raise
    except Exception:  # noqa: BLE001 — fail closed without leaking database details
        raise BudgetError(
            "AI paused: budget ledger is unavailable; no new paid call was authorized."
        ) from None


def _totals(conn, owner_id, now):
    from zylch.storage.models import LlmReservation, LlmUsage

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    costs = conn.execute(select(LlmUsage.est_cost_usd).where(LlmUsage.ts >= midnight)).scalars()
    # The profile database is the allowance boundary. Legacy rows carry email
    # owners, which can change; partitioning by owner would reopen allowance.
    spent = sum(micro_usd(cost) for cost in costs)
    holds = conn.execute(
        select(LlmReservation.reserved_micro_usd).where(LlmReservation.settled_at.is_(None))
    ).scalars()
    reserved = 0
    for value in holds:
        if type(value) is not int or value < 0:
            raise BudgetError("AI paused: budget ledger contains an invalid reservation.")
        reserved += value
    return spent, reserved, midnight + timedelta(days=1)


def _pricing_fault(conn):
    """A persisted bound breach invalidates further automatic admission."""
    from zylch.storage.models import LlmReservation, LlmUsage

    return (
        conn.execute(
            select(LlmReservation.id)
            .join(LlmUsage, LlmUsage.id == LlmReservation.id)
            .where(
                func.round(LlmUsage.est_cost_usd * 1_000_000) > LlmReservation.reserved_micro_usd
            )
            .limit(1)
        ).first()
        is not None
    )


def reserve(request_kwargs, transport, *, quote=None):
    from zylch.llm.usage import current_call_site
    from zylch.storage.models import LlmReservation

    owner_id = os.environ.get("OWNER_ID", "").strip()
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise BudgetError("AI paused: account identity is unavailable.")
    if transport == "proxy":
        from .bounded_proxy import validate_quote
        amount = validate_quote(request_kwargs, quote, owner_id)
    else:
        amount = request_bound(request_kwargs, transport)
    reservation = Reservation(
        str(uuid4()), owner_id, request_kwargs["model"], transport, amount, current_call_site()
    )
    with _transaction() as conn:
        cap = _budget()
        now = _now()
        spent, held, reset = _totals(conn, owner_id, now)
        if _pricing_fault(conn):
            raise BudgetError(
                "AI paused: recorded provider usage exceeded its bound; pricing reconciliation is required."
            )
        if cap == 0 or spent + held + amount > cap:
            raise BudgetError(
                f"AI paused: daily budget ${cap / 1e6:.2f}; "
                f"used or reserved ${(spent + held) / 1e6:.2f}. "
                f"This request needs up to ${amount / 1e6:.2f}. "
                f"Daily usage resets at {reset.isoformat()}Z; unresolved calls remain reserved."
            )
        if transport == "proxy":
            from zylch.storage.models import LlmBillingAuthorization
            conn.execute(LlmBillingAuthorization.__table__.insert().values(
                reservation_id=reservation.id, quote=quote,
            ))
        conn.execute(
            LlmReservation.__table__.insert().values(
                id=reservation.id,
                owner_id=owner_id,
                created_at=now,
                model=reservation.model,
                transport=transport,
                call_site=reservation.call_site,
                reserved_micro_usd=amount,
            )
        )
    return reservation


def settle(reservation, response_usage, *, receipt=None):
    from zylch.storage.models import LlmReservation, LlmUsage

    if reservation.transport == "proxy":
        amount, counts = None, {}
    elif reservation.transport == "openrouter":
        from .openrouter_pricing import usage_cost as router_cost

        amount, counts = router_cost(reservation.model, response_usage)
    else:
        amount, counts = usage_cost(reservation.model, response_usage)
    with _transaction() as conn:
        row = (
            conn.execute(
                select(LlmReservation.__table__).where(LlmReservation.id == reservation.id)
            )
            .mappings()
            .one_or_none()
        )
        if row is None or any(
            row[key] != getattr(reservation, key)
            for key in ("owner_id", "model", "transport", "reserved_micro_usd", "call_site")
        ):
            raise BudgetError("AI paused: budget reservation does not match this request.")
        if row["settled_at"] is not None:
            return
        if reservation.transport == "proxy":
            from zylch.storage.models import LlmBillingAuthorization
            from .bounded_proxy import validate_receipt
            authorization = conn.execute(select(LlmBillingAuthorization.__table__).where(
                LlmBillingAuthorization.reservation_id == reservation.id
            )).mappings().one_or_none()
            if authorization is None:
                raise BudgetError("MrCall authorization missing; reservation retained.")
            amount = validate_receipt(reservation, authorization["quote"], receipt)
            # The verified debit receipt is authoritative even if token usage
            # was lost with a response. Reconciliation never fabricates tokens.
            counts = {}
            for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                value = response_usage.get(key, 0) if isinstance(response_usage, dict) else 0
                counts[key] = value if type(value) is int and value >= 0 else 0
            conn.execute(LlmBillingAuthorization.__table__.update().where(
                LlmBillingAuthorization.reservation_id == reservation.id
            ).values(receipt=receipt))
        now = _now()
        conn.execute(
            LlmUsage.__table__.insert().values(
                id=reservation.id,
                owner_id=reservation.owner_id,
                ts=now,
                model=reservation.model,
                transport=reservation.transport,
                call_site=reservation.call_site,
                est_cost_usd=amount / 1e6,
                **counts,
            )
        )
        conn.execute(
            LlmReservation.__table__.update()
            .where(LlmReservation.id == reservation.id)
            .values(settled_at=now)
        )
        # If actual usage exceeds its bound, account for the full liability;
        # future calls see it. Do not roll back an already incurred charge.
    if amount > reservation.reserved_micro_usd:
        raise BudgetError(
            "AI paused: provider usage exceeded its reserved estimate; recorded in full."
        )


def budget_snapshot(owner_id):
    with _transaction() as conn:
        cap = _budget()
        spent, held, reset = _totals(conn, owner_id, _now())
        fault = _pricing_fault(conn)
    exceeded = spent + held >= cap or fault
    return {
        "spent_usd": spent / 1e6,
        "budget_usd": cap / 1e6,
        "exceeded": exceeded,
        "reserved_usd": held / 1e6,
        "remaining_usd": 0.0 if fault else max(0, cap - spent - held) / 1e6,
        "pricing_fault": fault,
        "resets_at": reset.isoformat() + "Z",
        "paused": exceeded,
    }
