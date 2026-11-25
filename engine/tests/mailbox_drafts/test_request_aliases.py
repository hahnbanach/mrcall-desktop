"""Every accepted mailbox replay key remains bound after SQLite restart."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
import threading

import pytest
from sqlalchemy import create_engine, event, inspect, select

from zylch.services.mailbox_drafts import MailboxDraftError
from zylch.storage.mailbox_operations import MailboxOperations, RECEIPTS, ReceiptConflict, digest

fixture = runpy.run_path(str(Path(__file__).with_name('test_mailbox_service.py')))
OWNER = fixture['OWNER']
prepare = fixture['prepare']
service = fixture['service']
cleanup_test_data = fixture['cleanup_test_data']


class CountingProvider(fixture['Provider']):
    def __init__(self):
        super().__init__()
        self.reads = self.moves = 0
        self.lose_trash_ack = False

    def get_draft(self, identifier):
        self.reads += 1
        return super().get_draft(identifier)

    def trash_draft(self, identifier, **kwargs):
        self.moves += 1
        result = super().trash_draft(identifier, **kwargs)
        if self.lose_trash_ack:
            self.lose_trash_ack = False
            raise TimeoutError('Controlled lost acknowledgement')
        return result


def opened(tmp_path, provider, name='profile.db'):
    engine = create_engine('sqlite:///' + str(tmp_path / name))
    return engine, service((engine, provider))


def reserve(store, key, *, owner=OWNER, kind='send', target='draft-a', source='<source@example.test>', payload=None):
    return store.reserve(owner=owner, request_key=key, kind=kind, target=target, source=source,
                         payload_digest=digest([target] if payload is None else payload), message_id='<canonical@example.test>')


def test_recovery_alias_commits_before_cleanup_and_cannot_send_another_draft_after_restart(tmp_path, monkeypatch):
    provider = CountingProvider()
    engine, value = opened(tmp_path, provider)
    first = prepare(value)
    provider.fail_retirement = True
    original = value.send(first['id'], 'original-send-request-0001')
    assert original['draft_cleanup']['state'] == 'pending' and provider.transmissions == 1
    alias = 'new-send-alias-request-0002'
    assert value.send_status(first['id'], alias)['state'] == 'not_found' and value.operation(alias) is None
    provider.fail_retirement = False
    actual_sent = provider.sent
    def checked(message_id):
        external_engine = create_engine('sqlite:///' + str(tmp_path / 'profile.db'))
        try:assert MailboxOperations(external_engine).read(OWNER, alias)['id'] == original['operation_id']
        finally:external_engine.dispose()
        return actual_sent(message_id)
    monkeypatch.setattr(provider, 'sent', checked)
    result = value.send(first['id'], alias)
    assert all(result[key] == original[key] for key in ('operation_id', 'request_key', 'message_id'))
    assert result['draft_cleanup']['state'] == 'completed' and provider.transmissions == provider.moves == 1
    engine.dispose()
    _, value = opened(tmp_path, provider)
    assert value.operation(alias)['id'] == original['operation_id']
    assert value.send_status(first['id'], alias)['operation_id'] == original['operation_id']
    other = value.create(['second@example.test'], 'Second synthetic', 'Second synthetic body', request_key='prepare-second-request-0003')
    before = (provider.transmissions, provider.creations, provider.moves, provider.reads)
    with pytest.raises(MailboxDraftError, match='request_key_payload_conflict'):value.send(other['id'], alias)
    assert (provider.transmissions, provider.creations, provider.moves, provider.reads) == before
    assert provider.creations == 2 and provider.transmissions == 1



def test_original_reproducer_alias_cannot_rebind_after_full_sqlite_reopen(tmp_path):
    provider = CountingProvider()
    engine, value = opened(tmp_path, provider)
    first = prepare(value)
    provider.fail_retirement = True
    original = value.send(first['id'], 'original-reproducer-send-0001')
    provider.fail_retirement = False
    recovered = value.send(first['id'], 'original-reproducer-alias-0002')
    assert recovered['draft_cleanup']['state'] == 'completed'
    assert recovered['operation_id'] == original['operation_id'] and provider.transmissions == 1
    engine.dispose()
    _, value = opened(tmp_path, provider)
    binding = value.operation('original-reproducer-alias-0002')
    assert binding is not None, 'Accepted recovery key disappeared after SQLite reopen'
    assert binding['id'] == original['operation_id']
    other = value.create(['second@example.test'], 'Second', 'Independent synthetic body', request_key='original-reproducer-create-0003')
    with pytest.raises(MailboxDraftError, match='request_key_payload_conflict'):
        value.send(other['id'], 'original-reproducer-alias-0002')
    assert provider.transmissions == 1

def test_missing_draft_concurrent_visibility_fallback_binds_alias(tmp_path, monkeypatch):
    provider = CountingProvider()
    engine, value = opened(tmp_path, provider)
    draft = prepare(value)
    original = value.send(draft['id'], 'race-original-send-key-0001')
    actual = value.operations.for_draft
    seen = []
    def initially_unavailable(owner, target, kind='send', **kwargs):
        if kind == 'send' and not seen:
            seen.append(True)
            return None
        return actual(owner, target, kind, **kwargs)
    monkeypatch.setattr(value.operations, 'for_draft', initially_unavailable)
    assert value.send(draft['id'], 'race-recovery-alias-key-0002')['operation_id'] == original['operation_id']
    engine.dispose()
    _, value = opened(tmp_path, provider)
    assert value.operation('race-recovery-alias-key-0002')['id'] == original['operation_id']
    assert provider.transmissions == 1


def test_trash_alias_survives_restart_without_second_move(tmp_path):
    provider = CountingProvider()
    engine, value = opened(tmp_path, provider)
    draft = prepare(value)
    provider.lose_trash_ack = True
    original = value.trash(draft['id'], 'original-trash-request-0001')
    assert original['state'] == 'unconfirmed' and provider.moves == 1
    result = value.trash(draft['id'], 'new-trash-alias-request-0002')
    assert result['ok'] and result['operation_id'] == original['operation_id'] and provider.moves == 1
    engine.dispose()
    _, value = opened(tmp_path, provider)
    assert value.operation('new-trash-alias-request-0002')['id'] == original['operation_id']
    other = value.create(['other@example.test'], 'Other', 'Other synthetic body', request_key='other-create-request-0003')
    before = (provider.moves, provider.creations, provider.reads)
    with pytest.raises(MailboxDraftError, match='request_key_payload_conflict'):value.trash(other['id'], 'new-trash-alias-request-0002')
    assert (provider.moves, provider.creations, provider.reads) == before and provider.transmissions == 0


@pytest.mark.parametrize('change', [dict(kind='trash'), dict(target='other-draft'), dict(source='<other@example.test>'), dict(payload=['changed'])])
def test_bound_alias_refuses_changed_kind_target_source_or_payload(tmp_path, change):
    store = MailboxOperations(create_engine('sqlite:///' + str(tmp_path / 'binding.db')))
    original, _ = reserve(store, 'canonical-binding-key-0001')
    result, token = reserve(store, 'valid-alias-binding-key-0002')
    assert result['id'] == original['id'] and token is None
    with pytest.raises(ReceiptConflict, match='request_key_payload_conflict'):reserve(store, 'valid-alias-binding-key-0002', **change)
    if not set(change) & {'kind', 'target'}:
        with pytest.raises(ReceiptConflict, match='request_key_payload_conflict'):reserve(store, 'new-conflicting-alias-key-0003', **change)
        assert store.read(OWNER, 'new-conflicting-alias-key-0003') is None


@pytest.mark.parametrize('kind', ['create', 'update', 'trash', 'send_message'])
def test_foreign_kind_key_refuses_before_recovery_provider_work(tmp_path, kind):
    provider = CountingProvider()
    _, value = opened(tmp_path, provider)
    draft = prepare(value)
    provider.fail_retirement = True
    value.send(draft['id'], 'original-kind-send-key-0001')
    reserve(value.operations, 'already-owned-other-key-0002', kind=kind, target='other-target', source='')
    before = (provider.reads, provider.retirement_attempts, provider.transmissions, provider.creations)
    with pytest.raises(MailboxDraftError, match='request_key_payload_conflict'):value.send(draft['id'], 'already-owned-other-key-0002')
    assert (provider.reads, provider.retirement_attempts, provider.transmissions, provider.creations) == before


def test_concurrent_same_alias_claims_return_one_original_operation(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'concurrent.db'))
    stores = [MailboxOperations(engine) for _ in range(6)]
    original, _ = reserve(stores[0], 'concurrent-canonical-key-0001')
    barrier = threading.Barrier(6)
    def claim(store):
        barrier.wait()
        return store.bind_recovery(owner=OWNER, request_key='concurrent-same-alias-key-0002',
            receipt_id=original['id'], kind='send', target=original['target']), None
    with ThreadPoolExecutor(max_workers=6) as pool:results = list(pool.map(claim, stores))
    assert all(row['id'] == original['id'] and token is None for row, token in results)
    with engine.connect() as conn:
        assert len(conn.execute(select(RECEIPTS)).all()) == 1
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM mailbox_operation_request_aliases').scalar_one() == 1
    engine.dispose()
    store = MailboxOperations(create_engine('sqlite:///' + str(tmp_path / 'concurrent.db')))
    assert store.read(OWNER, 'concurrent-same-alias-key-0002')['id'] == original['id']


def test_alias_and_new_operation_race_share_one_key_namespace(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'namespace.db'))
    stores = [MailboxOperations(engine), MailboxOperations(engine)]
    original, _ = reserve(stores[0], 'namespace-canonical-key-0001')
    barrier = threading.Barrier(2)
    def compete(index):
        barrier.wait()
        options = {} if index == 0 else dict(kind='create', target='other-target', source='')
        try:
            if index == 0:
                return stores[index].bind_recovery(owner=OWNER, request_key='namespace-contested-key-0002',
                    receipt_id=original['id'], kind='send', target=original['target']), None
            return reserve(stores[index], 'namespace-contested-key-0002', **options)
        except ReceiptConflict as error:return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:results = list(pool.map(compete, [0, 1]))
    successes = [result for result in results if isinstance(result, tuple)]
    assert len(successes) == 1 and 'request_key_payload_conflict' in results
    assert stores[0].read(OWNER, 'namespace-contested-key-0002')['id'] == successes[0][0]['id']


def test_aliases_are_owner_scoped_and_cannot_reference_another_owner(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'owners.db'))
    store = MailboxOperations(engine)
    first, _ = reserve(store, 'first-owner-canonical-key-0001')
    second, _ = reserve(store, 'second-owner-canonical-key-0001', owner='second@example.test')
    reserve(store, 'shared-alias-request-key-0002')
    reserve(store, 'shared-alias-request-key-0002', owner='second@example.test')
    assert store.read(OWNER, 'shared-alias-request-key-0002')['id'] == first['id']
    assert store.read('second@example.test', 'shared-alias-request-key-0002')['id'] == second['id']
    assert store.read('outsider@example.test', 'shared-alias-request-key-0002') is None
    with engine.begin() as conn:conn.exec_driver_sql('INSERT INTO mailbox_operation_request_aliases VALUES (?,?,?,?)', ('outsider@example.test', 'foreign-owner-alias-key-0003', first['id'], 0.0))
    with pytest.raises(ReceiptConflict, match='mailbox_request_alias_invalid'):store.read('outsider@example.test', 'foreign-owner-alias-key-0003')


def test_existing_receipt_schema_is_additively_compatible_and_body_free(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'legacy.db'))
    RECEIPTS.create(engine)
    row = dict(id='old-operation', owner=OWNER, request_key='old-canonical-request-0001', kind='send', target='draft-a', source='<source@example.test>', payload_digest=digest(['draft-a']), message_id='<old@example.test>', draft_id=None, stage='unconfirmed', executor='old-token', result=None, created_at=1.0, updated_at=1.0)
    with engine.begin() as conn:conn.execute(RECEIPTS.insert().values(**row))
    store = MailboxOperations(engine)
    result, token = reserve(store, 'old-operation-new-alias-0002')
    assert token is None and result['id'] == row['id'] and result['message_id'] == row['message_id']
    with engine.connect() as conn:assert dict(conn.execute(select(RECEIPTS)).mappings().one()) == row
    assert {column['name'] for column in inspect(engine).get_columns('mailbox_operation_request_aliases')} == {'owner', 'request_key', 'receipt_id', 'created_at'}


def test_migrated_send_payload_encoding_keeps_friendly_alias_recovery(tmp_path):
    provider = CountingProvider()
    engine, value = opened(tmp_path, provider)
    draft = prepare(value)
    provider.fail_retirement = True
    original = value.send(draft['id'], 'legacy-format-original-key-0001')
    legacy_digest = digest({'legacy_send_id': 'historical-operation'})
    with engine.begin() as conn:
        conn.execute(RECEIPTS.update().where(RECEIPTS.c.id == original['operation_id']).values(payload_digest=legacy_digest))
    provider.fail_retirement = False
    result = value.send(draft['id'], 'legacy-format-new-alias-0002')
    assert result['operation_id'] == original['operation_id'] and result['draft_cleanup']['state'] == 'completed'
    engine.dispose()
    _, value = opened(tmp_path, provider)
    rebound = value.operation('legacy-format-new-alias-0002')
    assert rebound['id'] == original['operation_id'] and rebound['payload_digest'] == legacy_digest
    assert provider.transmissions == provider.moves == 1


def test_observed_canonical_state_change_never_creates_another_send(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'state-change.db'))
    store = MailboxOperations(engine)
    original, token = reserve(store, 'state-change-canonical-key-0001')
    store.advance(original, token, 'not_dispatched')
    bound = store.bind_recovery(owner=OWNER, request_key='state-change-alias-key-0002',
        receipt_id=original['id'], kind='send', target=original['target'])
    assert bound['id'] == original['id'] and bound['stage'] == 'not_dispatched'
    with engine.connect() as conn:assert len(conn.execute(select(RECEIPTS)).all()) == 1
    with engine.begin() as conn:
        conn.exec_driver_sql('DELETE FROM mailbox_operation_request_aliases')
        conn.execute(RECEIPTS.delete())
    with pytest.raises(ReceiptConflict, match='mailbox_operation_not_found'):
        store.bind_recovery(owner=OWNER, request_key='deleted-operation-alias-key-0003',
            receipt_id=original['id'], kind='send', target=original['target'])
    assert store.read(OWNER, 'deleted-operation-alias-key-0003') is None
    with engine.connect() as conn:assert not conn.execute(select(RECEIPTS)).all()


def test_concurrent_first_open_adds_alias_schema_without_losing_existing_receipt(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'first-open.db')
    initial = create_engine(url)
    RECEIPTS.create(initial)
    row = dict(id='dev12-operation', owner=OWNER, request_key='dev12-canonical-key-0001', kind='send',
        target='draft-a', source='<source@example.test>', payload_digest='old-digest',
        message_id='<old@example.test>', draft_id=None, stage='unconfirmed', executor='old-token',
        result=None, created_at=1.0, updated_at=1.0)
    with initial.begin() as conn:conn.execute(RECEIPTS.insert().values(**row))
    initial.dispose()
    boundary = threading.Barrier(2)
    def first_open(_):
        engine = create_engine(url)
        @event.listens_for(engine, 'before_cursor_execute')
        def simultaneous_create(conn, cursor, statement, parameters, context, many):
            if 'CREATE TABLE' in statement and 'mailbox_operation_request_aliases' in statement:
                boundary.wait(timeout=5)
        try:
            store = MailboxOperations(engine)
            assert store.read(OWNER, row['request_key'])['id'] == row['id']
        finally:engine.dispose()
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(first_open, [0, 1]))
    reopened = create_engine(url)
    try:
        with reopened.connect() as conn:assert dict(conn.execute(select(RECEIPTS)).mappings().one()) == row
        assert 'mailbox_operation_request_aliases' in inspect(reopened).get_table_names()
    finally:reopened.dispose()
