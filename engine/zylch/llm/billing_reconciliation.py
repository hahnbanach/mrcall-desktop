"""Recover known credit receipts through read-only status; never retry inference."""
from sqlalchemy import select

from .budget import Reservation, _transaction, settle
from .budget_pricing import BudgetError


def pending_credit_reservations(cursor=None):
    from zylch.storage.models import LlmReservation
    with _transaction() as conn:
        query = select(LlmReservation.__table__).where(
            LlmReservation.transport == 'proxy', LlmReservation.settled_at.is_(None))
        if cursor:
            query = query.where(LlmReservation.id > cursor)
        rows = conn.execute(query.order_by(LlmReservation.id).limit(10)).mappings().all()
    return [Reservation(**{key: row[key] for key in Reservation.__dataclass_fields__}) for row in rows]


def reconcile(client, *, cursor=None):
    recovered, unresolved = 0, 0
    reservations = pending_credit_reservations(cursor)
    for reservation in reservations:
        try:
            state = client.status(reservation.id)
            if not isinstance(state, dict) or state.get('state') != 'settled':
                unresolved += 1
                continue
            settle(reservation, None, receipt=state.get('receipt'))
            recovered += 1
        except BudgetError:
            unresolved += 1
    return {'recovered': recovered, 'unresolved': unresolved,
            'next_cursor': reservations[-1].id if len(reservations) == 10 else None,
            'message': 'Only confirmed receipts release reservations. No AI request was repeated.'}
