"""Native Stripe lifecycle and explicit private read RPCs."""

from zylch.qonto.logging import private_rpc
from zylch.stripe import connection


async def stripe_status(params, notify):
    """stripe.status() -> safe connection metadata."""
    return connection.status()


async def stripe_test(params, notify):
    """stripe.test(api_key) -> tested account, mode and expiring challenge."""
    return await connection.test(params)


async def stripe_connect(params, notify):
    """stripe.connect(api_key, challenge_id, authority_confirmed) -> saved connection."""
    return await connection.connect(params)


async def stripe_disconnect(params, notify):
    """stripe.disconnect() -> removal of encrypted credential and generation advance."""
    return connection.disconnect()


async def stripe_customers(params, notify):
    """stripe.customers(limit=25, starting_after?, email?) -> bounded customer evidence."""
    return await connection.read("customers", params)


async def stripe_payments(params, notify):
    """stripe.payments(limit=25, starting_after?, customer?) -> bounded payment-intent evidence."""
    return await connection.read("payments", params)


async def stripe_invoices(params, notify):
    """stripe.invoices(limit=25, starting_after?, customer?) -> bounded invoice evidence."""
    return await connection.read("invoices", params)


async def stripe_subscriptions(params, notify):
    """stripe.subscriptions(limit=25, starting_after?, customer?) -> bounded subscription evidence."""
    return await connection.read("subscriptions", params)


async def stripe_detail(params, notify):
    """stripe.detail(resource, id) -> single bounded resource evidence."""
    return await connection.read("detail", params)


METHODS = {
    "stripe." + name: private_rpc(globals()["stripe_" + name])
    for name in (
        "status",
        "test",
        "connect",
        "disconnect",
        "customers",
        "payments",
        "invoices",
        "subscriptions",
        "detail",
    )
}
