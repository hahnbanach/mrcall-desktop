"""Small durable M1 test ledger, separate from customer/profile business data.

No reset/refund API: at most six attempted accepts and USD5 reserved for this
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
            held, count = db.execute(
                select(func.coalesce(func.sum(SmokeCall.reserved_microusd), 0), func.count())
                .select_from(SmokeCall)
                .where(SmokeCall.reserved_microusd > 0)
            ).one()
            unresolved = db.execute(
                select(SmokeCall.session_id).where(
                    SmokeCall.state.in_(["accepting", "active", "uncertain"])
                )
            ).first()
            accept = allowed and not unresolved and count < self.max_calls
            accept = accept and held + self.reservation <= 5_000_000
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
                        SmokeCall.state.in_(["accepting", "active", "uncertain"])
                    )
                ).scalars()
            )

    def rows(self) -> list[dict]:
        with self.engine.connect() as db:
            return [dict(r) for r in db.execute(select(SmokeCall.__table__)).mappings()]

    def close(self) -> None:
        self.engine.dispose()
