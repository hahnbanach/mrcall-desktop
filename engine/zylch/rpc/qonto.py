"""Native Qonto lifecycle RPCs; no owner or company override is accepted."""

from zylch.qonto import connection
from zylch.qonto.logging import private_rpc


async def qonto_test(params, notify):
    """qonto.test(credential_source="input", login?, api_key?, account_ids?) -> tested organization and confirmation challenge."""
    return await connection.test(params)


async def qonto_connect(params, notify):
    """qonto.connect(challenge_id, account_ids, authority_confirmed, consent_version, credential_source="input", login?, api_key?) -> connection status."""
    return await connection.connect(params)


async def qonto_status(params, notify):
    """qonto.status() -> safe connection and bootstrap availability."""
    return connection.status()


async def qonto_disconnect(params, notify):
    """qonto.disconnect() -> application credential removal and retained bootstrap availability."""
    return connection.disconnect()


async def qonto_sync(params, notify):
    """qonto.sync() -> bounded source-only refresh and durable partial coverage."""
    from zylch.qonto.sync import run

    return await run()


async def qonto_delete_imported_data(params, notify):
    """qonto.delete_imported_data(confirmed) -> deletion of private imported source data."""
    return connection.delete_imported_data(params)


async def _read(operation, params):
    from zylch.qonto import guard, history, reads

    result = await getattr(reads, operation)(params)
    authority, binding = guard.active_binding()
    if binding.generation != result["generation"]:
        from zylch.qonto.errors import QontoError

        raise QontoError("generation_changed")
    history.record_disclosed_evidence(result, authority, binding)
    return result


async def qonto_accounts(params, notify):
    """qonto.accounts(account_ids?) -> authorized selected accounts and provider balances."""
    return await _read("accounts", params)


async def qonto_transactions(params, notify):
    """qonto.transactions(date_basis, date_from, date_to, statuses, account_ids?, currency?, side?, page=1, page_size=25) -> bounded transactions and coverage."""
    return await _read("transactions", params)


async def qonto_transaction(params, notify):
    """qonto.transaction(source_id) -> authorized bounded source evidence."""
    return await _read("transaction", params)


async def qonto_summary(params, notify):
    """qonto.summary(date_basis, date_from, date_to, statuses, account_ids?, currency?, side?) -> exact grouped period flow, never account balance."""
    return await _read("summary", params)


async def qonto_prepare(params, notify):
    """qonto.prepare(resume=False) -> one bounded private finance preparation batch."""
    from zylch.qonto import preparation
    from zylch.rpc.methods import register_socket_bound_task

    register_socket_bound_task()
    return await preparation.run(params)


async def qonto_publication_preview(params, notify):
    """qonto.publication_preview() -> minimal fact, audience disclosure and bound confirmation preview."""
    from zylch.qonto import publication

    return await publication.preview(params)


async def qonto_publish(params, notify):
    """qonto.publish(preview_id?, confirmed?, resume=False) -> consented minimal company fact publication outcome or safe refusal."""
    from zylch.qonto import publication
    from zylch.rpc.methods import register_socket_bound_task

    register_socket_bound_task()
    return await publication.publish(params)


METHODS = {
    "qonto.prepare": qonto_prepare,
    "qonto.publication_preview": qonto_publication_preview,
    "qonto.publish": qonto_publish,
    "qonto.accounts": qonto_accounts,
    "qonto.transactions": qonto_transactions,
    "qonto.transaction": qonto_transaction,
    "qonto.summary": qonto_summary,
    "qonto.test": qonto_test,
    "qonto.connect": qonto_connect,
    "qonto.status": qonto_status,
    "qonto.disconnect": qonto_disconnect,
    "qonto.sync": qonto_sync,
    "qonto.delete_imported_data": qonto_delete_imported_data,
}

METHODS = {name: private_rpc(handler) for name, handler in METHODS.items()}
