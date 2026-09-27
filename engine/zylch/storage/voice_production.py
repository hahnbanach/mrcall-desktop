"""Separate durable production voice holds and accrued provider exposure."""

from __future__ import annotations

import math
import json
import re
import time
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from sqlalchemy import Column, Integer, JSON, String, create_engine, select

from .voice_smoke import Base, SmokeCall, SmokeCarrier, SmokeLedger, SmokeRun


class ProductionMeter(Base):
    __tablename__ = "production_voice_meter"
    session_id = Column(String, primary_key=True)
    state = Column(String, nullable=False)
    accrued_microusd = Column(Integer, nullable=False, default=0)
    hold_increase_microusd = Column(Integer, nullable=False, default=0)
    provider_usage = Column(JSON, nullable=True)
    carrier_receipt = Column(JSON, nullable=True)
    conversation_uuid = Column(String, nullable=False, unique=True)
    reconciliation_state = Column(String, nullable=False, default="pending")
    updated_at = Column(Integer, nullable=False)


class ProductionVoiceLedger(SmokeLedger):
    """No lifetime budget/count ceiling; one unresolved call at a time."""

    requires_conversation_uuid = True

    def __init__(self, path: Path, policy_id: str, reservation: int,
                 rate_per_minute: int = 70_000):
        if reservation < 10_000_000:
            raise ValueError("insufficient production voice reserve")
        if rate_per_minute <= 0:
            raise ValueError("invalid production exposure rate")
        self.reservation = reservation
        self.rate_per_minute = rate_per_minute
        self.max_calls = 1  # active capacity; unlimited mode ignores lifetime count
        self.unlimited = True
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 2})
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            saved = db.execute(select(SmokeRun.policy_id)).scalar_one_or_none()
            if saved is None:
                db.execute(SmokeRun.__table__.insert().values(id=1, policy_id=policy_id))
            elif saved != policy_id:
                raise ValueError("production voice binding changed; preserve ledger")

    def reserve_carrier(self, carrier_id: str, token_hash: str, *, allowed: bool,
                        conversation_uuid: str | None = None) -> bool:
        if not isinstance(conversation_uuid, str) or not re.fullmatch(
            r"CON-[A-Za-z0-9-]{1,100}", conversation_uuid
        ):
            raise ValueError("missing signed carrier conversation")
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            if db.execute(select(SmokeCarrier.carrier_id).where(
                SmokeCarrier.carrier_id == carrier_id
            )).first():
                return False
            accepted = allowed and self._available(db)
            placeholder = "vonage:" + carrier_id
            db.execute(SmokeCall.__table__.insert().values(
                session_id=placeholder,
                state="carrier_waiting" if accepted else "rejected",
                reserved_microusd=self.reservation if accepted else 0,
                started_at=int(time.time()), evidence="{}",
            ))
            db.execute(SmokeCarrier.__table__.insert().values(
                carrier_id=carrier_id,
                token_hash=token_hash if accepted else None,
                session_id=placeholder,
            ))
            if accepted:
                db.execute(ProductionMeter.__table__.insert().values(
                    session_id=placeholder, state="carrier_waiting",
                    accrued_microusd=0, hold_increase_microusd=0,
                    conversation_uuid=conversation_uuid,
                    reconciliation_state="pending",
                    updated_at=int(time.time()),
                ))
            return accepted

    def _available(self, db) -> bool:
        if not super()._available(db):
            return False
        # A closed call can precede either provider's final evidence. Keep its
        # hold and refuse another paid admission until both receipts cover the
        # estimate; there is no numeric call or lifetime spending ceiling.
        settled = db.execute(select(
            SmokeCall.session_id, ProductionMeter.reconciliation_state
        ).outerjoin(
            ProductionMeter, ProductionMeter.session_id == SmokeCall.session_id
        ).where(
            SmokeCall.reserved_microusd > 0,
            SmokeCall.state.in_(["closed", "stopped"]),
        )).all()
        return all(state == "provisionally_covered" for _, state in settled)

    def admission_ready(self) -> bool:
        with self.engine.connect() as db:
            return self._available(db)

    def bind_carrier(self, session_id: str, token_hash: str | None, *, allowed: bool) -> str:
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            if db.execute(select(SmokeCall.session_id).where(
                SmokeCall.session_id == session_id
            )).first():
                return "duplicate"
            pending = (
                db.execute(
                    select(SmokeCarrier.carrier_id, SmokeCarrier.session_id)
                    .join(SmokeCall, SmokeCall.session_id == SmokeCarrier.session_id)
                    .where(
                        SmokeCarrier.token_hash == token_hash,
                        SmokeCall.state == "carrier_waiting",
                    )
                ).one_or_none()
                if token_hash and allowed else None
            )
            if pending and db.execute(select(SmokeCall.session_id).where(
                SmokeCall.session_id != pending.session_id,
                SmokeCall.state.in_(["carrier_waiting", "accepting", "active", "uncertain"]),
            )).first():
                pending = None
            if pending:
                placeholder = pending.session_id
                changed = db.execute(ProductionMeter.__table__.update().where(
                    ProductionMeter.session_id == placeholder,
                    ProductionMeter.state == "carrier_waiting",
                ).values(session_id=session_id, state="accepting",
                         updated_at=int(time.time())))
                if changed.rowcount != 1:
                    raise ValueError("production exposure meter missing")
                db.execute(SmokeCall.__table__.update().where(
                    SmokeCall.session_id == placeholder
                ).values(session_id=session_id, state="accepting"))
                db.execute(SmokeCarrier.__table__.update().where(
                    SmokeCarrier.carrier_id == pending.carrier_id
                ).values(session_id=session_id))
                return "accept"
            db.execute(SmokeCall.__table__.insert().values(
                session_id=session_id, state="rejecting", reserved_microusd=0,
                started_at=int(time.time()), evidence="{}",
            ))
            return "reject"

    def accrue(self, session_id: str, elapsed_seconds: float, rate_per_minute: int) -> None:
        """Persist incurred estimate and increase the hold before the next minute."""
        if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0 or rate_per_minute <= 0:
            raise ValueError("invalid exposure")
        accrued = math.ceil(elapsed_seconds * rate_per_minute / 60)
        next_exposure = math.ceil((elapsed_seconds + 60) * rate_per_minute / 60)
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            call = db.execute(select(SmokeCall.__table__).where(SmokeCall.session_id == session_id)).mappings().one()
            meter = db.execute(select(ProductionMeter.__table__).where(
                ProductionMeter.session_id == session_id
            )).mappings().one()
            if meter["state"] in {"closed", "stopped", "rejected"}:
                return
            new_hold = max(call["reserved_microusd"], next_exposure)
            increase = new_hold - call["reserved_microusd"]
            if increase:
                db.execute(SmokeCall.__table__.update().where(
                    SmokeCall.session_id == session_id
                ).values(reserved_microusd=new_hold))
            db.execute(ProductionMeter.__table__.update().where(
                ProductionMeter.session_id == session_id
            ).values(
                accrued_microusd=max(meter["accrued_microusd"], accrued),
                hold_increase_microusd=meter["hold_increase_microusd"] + increase,
                state="active",
                updated_at=int(time.time()),
            ))

    def record_provider_usage(self, session_id: str, *, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            return
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            call = db.execute(select(SmokeCall.__table__).where(
                SmokeCall.session_id == session_id
            )).mappings().one()
            meter = db.execute(select(ProductionMeter.__table__).where(
                ProductionMeter.session_id == session_id
            )).mappings().one()
            estimated = math.ceil(seconds * self.rate_per_minute / 60)
            receipt = meter["carrier_receipt"] or {}
            new_hold = max(
                call["reserved_microusd"],
                estimated + (receipt.get("usd_estimate_microusd") or 0),
            )
            if new_hold != call["reserved_microusd"]:
                db.execute(SmokeCall.__table__.update().where(
                    SmokeCall.session_id == session_id
                ).values(reserved_microusd=new_hold))
            db.execute(ProductionMeter.__table__.update().where(
                ProductionMeter.session_id == session_id
            ).values(
                provider_usage={"voice_seconds": seconds,
                                "combined_exposure_estimate_microusd": estimated},
                hold_increase_microusd=(meter["hold_increase_microusd"]
                                        + new_hold - call["reserved_microusd"]),
                reconciliation_state=("provisionally_covered"
                                      if receipt.get("covered")
                                      else "pending"),
                updated_at=int(time.time()),
            ))

    def record_carrier_receipt(self, carrier_id: str, *, conversation_uuid: str | None,
                               direction: str | None, status: str,
                               price: str | None, currency: str | None) -> None:
        if status not in {"completed", "failed", "busy", "rejected", "cancelled"}:
            return
        try:
            amount = Decimal(price) if price is not None else None
            if amount is not None and (not amount.is_finite() or amount < 0):
                return
        except (InvalidOperation, ValueError):
            return
        if not isinstance(conversation_uuid, str) or not re.fullmatch(
            r"CON-[A-Za-z0-9-]{1,100}", conversation_uuid
        ) or direction not in {"inbound", "outbound"}:
            return
        if currency is not None and currency not in {"USD", "EUR"}:
            return
        currency_source = "payload" if currency else "Vonage Voice webhook reference"
        currency = currency or "EUR"
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            meter = db.execute(select(ProductionMeter.__table__).where(
                ProductionMeter.conversation_uuid == conversation_uuid
            )).mappings().one_or_none()
            if meter is None:
                return
            session_id = meter["session_id"]
            call = db.execute(select(SmokeCall.__table__).where(
                SmokeCall.session_id == session_id
            )).mappings().one_or_none()
            if call is None or call["reserved_microusd"] == 0:
                return
            inbound_id = db.execute(select(SmokeCarrier.carrier_id).where(
                SmokeCarrier.session_id == session_id
            )).scalar_one_or_none()
            if inbound_id is None or (carrier_id == inbound_id) != (direction == "inbound"):
                return
            prior = meter["carrier_receipt"] or {}
            legs = dict(prior.get("legs") or {})
            legs[carrier_id] = {
                "status": status, "price": price, "currency": currency,
                "currency_source": currency_source, "direction": direction,
            }
            complete = [leg for leg in legs.values()
                        if leg["status"] == "completed" and leg["price"] is not None]
            covered = (
                len(complete) >= 2 and
                any(leg["direction"] == "inbound" for leg in complete) and
                any(leg["direction"] == "outbound" for leg in complete)
            )
            # Two USD per EUR is a deliberately padded *estimate*, not a
            # conversion or provider invoice. Unknown currency remains pending.
            carrier_usd_estimate = sum(
                int((Decimal(leg["price"]) *
                     (2 if leg["currency"] == "EUR" else 1) * 1_000_000)
                    .to_integral_value(rounding=ROUND_CEILING))
                for leg in complete
            )
            provider = meter["provider_usage"] or {}
            provider_estimate = math.ceil(
                provider.get("voice_seconds", 0) * self.rate_per_minute / 60
            )
            new_hold = max(
                call["reserved_microusd"],
                provider_estimate + (carrier_usd_estimate or 0),
            )
            if new_hold != call["reserved_microusd"]:
                db.execute(SmokeCall.__table__.update().where(
                    SmokeCall.session_id == session_id
                ).values(reserved_microusd=new_hold))
            db.execute(ProductionMeter.__table__.update().where(
                ProductionMeter.session_id == session_id
            ).values(
                carrier_receipt={"legs": legs, "covered": covered,
                                 "usd_estimate_microusd": carrier_usd_estimate},
                hold_increase_microusd=(meter["hold_increase_microusd"]
                                        + new_hold - call["reserved_microusd"]),
                reconciliation_state=("provisionally_covered"
                                      if covered and meter["provider_usage"]
                                      else "pending"),
                updated_at=int(time.time()),
            ))

    def finish(self, session_id: str, state: str, evidence: dict | None = None) -> None:
        if state not in {"active", "closed", "stopped", "uncertain", "rejected"}:
            raise ValueError("invalid production voice state")
        values = {"state": state}
        if evidence is not None:
            values["evidence"] = json.dumps(evidence, allow_nan=False)
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            meter = db.execute(select(ProductionMeter.__table__).where(
                ProductionMeter.session_id == session_id
            )).mappings().one_or_none()
            call = db.execute(select(SmokeCall.__table__).where(
                SmokeCall.session_id == session_id
            )).mappings().one_or_none()
            if call is not None and call["reserved_microusd"] > 0 and meter is None:
                # A crash between base carrier binding and meter binding must
                # never turn the positive hold into a closed, admissible row.
                raise ValueError("production exposure meter missing")
            if meter is not None and call is not None and evidence is not None:
                elapsed_ms = evidence.get("observed_elapsed_ms")
                if type(elapsed_ms) is int and elapsed_ms >= 0:
                    accrued = math.ceil(elapsed_ms * self.rate_per_minute / 60_000)
                    new_hold = max(call["reserved_microusd"], accrued)
                    db.execute(ProductionMeter.__table__.update().where(
                        ProductionMeter.session_id == session_id
                    ).values(
                        accrued_microusd=max(meter["accrued_microusd"], accrued),
                        hold_increase_microusd=(meter["hold_increase_microusd"]
                                                + new_hold - call["reserved_microusd"]),
                    ))
                    values["reserved_microusd"] = new_hold
            # The call and its exposure meter must have the same terminal state.
            # A partial close could allow a new paid call over an unresolved hold.
            db.execute(SmokeCall.__table__.update().where(
                SmokeCall.session_id == session_id
            ).values(**values))
            db.execute(ProductionMeter.__table__.update().where(
                ProductionMeter.session_id == session_id
            ).values(state=state, updated_at=int(time.time())))
