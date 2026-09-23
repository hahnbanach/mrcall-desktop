"""Small durable M1 test ledger, separate from customer/profile business data.

No reset/refund API: at most six funded attempts and USD5 reserved for this
supervised experiment, across restarts and UTC midnight. Uncertain calls block
further admission. Use one profile lock for the process and an immediate SQLite
transaction for admission. Store no secrets, caller numbers, audio or transcripts.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from sqlalchemy import Column, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SmokeRun(Base):
    __tablename__ = "smoke_run"
    id = Column(Integer, primary_key=True)
    policy_id = Column(String, nullable=False)


class SmokeCall(Base):
    __tablename__ = "smoke_calls"
    session_id = Column(String, primary_key=True)
    state = Column(String, nullable=False)
    reserved_microusd = Column(Integer, nullable=False)
    started_at = Column(Integer, nullable=False)
    evidence = Column(Text, nullable=False, default="{}")


class SmokeCarrier(Base):
    __tablename__ = "smoke_carrier"
    carrier_id = Column(String, primary_key=True)
    token_hash = Column(String, nullable=True, unique=True)
    session_id = Column(String, nullable=False)


class SmokeLedger:
    """Calls are keyed by session, not delivery ID, so redelivery never accepts twice."""

    def __init__(self, path: Path, policy_id: str, reservation: int, max_calls: int) -> None:
        if not 0 < reservation <= 5_000_000 or not 1 <= max_calls <= 6:
            raise ValueError("invalid smoke limits")
        self.reservation = reservation
        self.max_calls = max_calls
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 2})
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            saved = db.execute(select(SmokeRun.policy_id)).scalar_one_or_none()
            if saved is None:
                db.execute(SmokeRun.__table__.insert().values(id=1, policy_id=policy_id))
            elif saved != policy_id:
                raise ValueError(
                    "smoke run configuration changed; retain ledger and reconcile first"
                )

    def admit(self, session_id: str, *, allowed: bool) -> str:
        """Commit the hold *before* any network dispatch; rejected decisions also dedupe."""
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            if db.execute(
                select(SmokeCall.session_id).where(SmokeCall.session_id == session_id)
            ).first():
                return "duplicate"
            accept = allowed and self._available(db)
            db.execute(
                SmokeCall.__table__.insert().values(
                    session_id=session_id,
                    state="accepting" if accept else "rejecting",
                    reserved_microusd=self.reservation if accept else 0,
                    started_at=int(time.time()),
                    evidence="{}",
                )
            )
            return "accept" if accept else "reject"

    def _available(self, db) -> bool:
        held, count = db.execute(
            select(func.coalesce(func.sum(SmokeCall.reserved_microusd), 0), func.count())
            .select_from(SmokeCall)
            .where(SmokeCall.reserved_microusd > 0)
        ).one()
        unresolved = db.execute(
            select(SmokeCall.session_id).where(
                SmokeCall.state.in_(["carrier_waiting", "accepting", "active", "uncertain"])
            )
        ).first()
        return not unresolved and count < self.max_calls and held + self.reservation <= 5_000_000

    def reserve_carrier(self, carrier_id: str, token_hash: str, *, allowed: bool) -> bool:
        """Commit before emitting any NCCO; retries never issue another connect."""
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            if db.execute(
                select(SmokeCarrier.carrier_id).where(SmokeCarrier.carrier_id == carrier_id)
            ).first():
                return False
            accept = allowed and self._available(db)
            placeholder = "vonage:" + carrier_id
            db.execute(
                SmokeCall.__table__.insert().values(
                    session_id=placeholder,
                    state="carrier_waiting" if accept else "rejected",
                    reserved_microusd=self.reservation if accept else 0,
                    started_at=int(time.time()),
                    evidence="{}",
                )
            )
            db.execute(
                SmokeCarrier.__table__.insert().values(
                    carrier_id=carrier_id,
                    token_hash=token_hash if accept else None,
                    session_id=placeholder,
                )
            )
            return accept

    def bind_carrier(self, session_id: str, token_hash: str | None, *, allowed: bool) -> str:
        """Consume one pending correlation nonce; reuse its hold, never reserve twice."""
        with self.engine.begin() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            if db.execute(
                select(SmokeCall.session_id).where(SmokeCall.session_id == session_id)
            ).first():
                return "duplicate"
            pending = (
                db.execute(
                    select(SmokeCarrier.session_id)
                    .join(SmokeCall, SmokeCall.session_id == SmokeCarrier.session_id)
                    .where(
                        SmokeCarrier.token_hash == token_hash,
                        SmokeCall.state == "carrier_waiting",
                    )
                ).scalar_one_or_none()
                if token_hash and allowed
                else None
            )
            if (
                pending
                and db.execute(
                    select(SmokeCall.session_id).where(
                        SmokeCall.session_id != pending,
                        SmokeCall.state.in_(
                            ["carrier_waiting", "accepting", "active", "uncertain"]
                        ),
                    )
                ).first()
            ):
                pending = None
            if pending:
                db.execute(
                    SmokeCall.__table__.update()
                    .where(SmokeCall.session_id == pending)
                    .values(session_id=session_id, state="accepting")
                )
                db.execute(
                    SmokeCarrier.__table__.update()
                    .where(SmokeCarrier.session_id == pending)
                    .values(session_id=session_id)
                )
                return "accept"
            db.execute(
                SmokeCall.__table__.insert().values(
                    session_id=session_id,
                    state="rejecting",
                    reserved_microusd=0,
                    started_at=int(time.time()),
                    evidence="{}",
                )
            )
            return "reject"

    def finish(self, session_id: str, state: str, evidence: dict | None = None) -> None:
        if state not in {"active", "closed", "stopped", "uncertain", "rejected"}:
            raise ValueError("invalid smoke state")
        values = {"state": state}
        if evidence is not None:
            values["evidence"] = json.dumps(evidence, allow_nan=False)
        with self.engine.begin() as db:
            db.execute(
                SmokeCall.__table__.update()
                .where(SmokeCall.session_id == session_id)
                .values(**values)
            )

    def unresolved(self) -> list[str]:
        with self.engine.connect() as db:
            return list(
                db.execute(
                    select(SmokeCall.session_id).where(
                        SmokeCall.state.in_(["carrier_waiting", "accepting", "active", "uncertain"])
                    )
                ).scalars()
            )

    def rows(self) -> list[dict]:
        with self.engine.connect() as db:
            return [dict(r) for r in db.execute(select(SmokeCall.__table__)).mappings()]

    def close(self) -> None:
        self.engine.dispose()
