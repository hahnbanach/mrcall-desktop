"""Real SQLite company transactions; fixtures are not actual-client acceptance."""
import base64
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

from sqlalchemy import inspect, insert, select, update
from zylch.services import operator_rule_changes as changes
from zylch.services import operator_rule_proposals as bindings
from zylch.services import operator_instructions as instructions
from zylch.services import project_store as projects
from engine.tests import test_operator_rule_proposals as fixtures


class RuleChangeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RuleProposalTests()
        self.fixture.setUp()
        self.engine = self.fixture.engine
        self.actor = self.fixture.actor
        self.path = self.fixture.path
        for path in ('mail/third@example.test.md', 'mail/fourth@example.test.md'):
            instructions.store('company-a', path, base64.b64encode(b'Identity').decode(), 0, self.actor.mailbox)
        with self.engine.begin() as conn:
            bindings.MANAGED.create(conn)
            conn.execute(insert(bindings.MANAGED).values(space_id='company-a', mode='managed',
                import_digest='controlled-fixture', imported_at=1, profile_uid='uid-a'))

    def tearDown(self):
        self.fixture.tearDown()

    def save(self, text='New exact caffè rule\n', key='test-rule-save-0001', base=1, target='procedures.md', actor=None):
        return changes.save_rule(key, target, text, base, actor or self.actor)

    def current(self, path='procedures.md'):
        return changes.read_rules(self.actor, path)['documents'][0]

    def test_all_six_paths_and_readonly_queries_create_no_schema(self):
        before = set(inspect(self.engine).get_table_names())
        docs = changes.read_rules(self.actor)['documents']
        self.assertEqual(len(docs), 6)
        self.assertEqual(changes.rule_history(self.path, 20, self.actor)['current_revision'], 1)
        with self.assertRaises(projects.ProjectError):
            changes.rule_change_status(self.actor, request_key='missing-change-0001')
        self.assertEqual(before, set(inspect(self.engine).get_table_names()))
        for index, doc in enumerate(docs):
            saved = self.save(target=doc['path'], key=f'all-six-paths-{index:04d}')
            self.assertEqual(saved['state'], 'saved')
            self.assertEqual(self.current(doc['path'])['revision'], 2)

    def test_exact_save_retry_and_recovery(self):
        result = self.save()
        self.assertEqual((result['state'], result['revision']), ('saved', 2))
        self.assertEqual(self.save(), result)
        self.assertEqual(changes.rule_change_status(self.actor, operation_id=result['operation_id']), result)
        self.assertEqual(changes.rule_change_status(self.actor, request_key=result['request_key']), result)
        self.assertEqual(self.current()['content'], 'New exact caffè rule\n')
        self.assertEqual(result['authority'], 'delegated_client_grant')
        self.assertNotIsInstance(self.actor, bindings.HumanBinding)

    def test_same_key_changed_payload_refused(self):
        self.save()
        with self.assertRaises(projects.ProjectError):
            self.save(text='Different payload')
        self.assertEqual(self.current()['revision'], 2)

    def test_strict_stale_identical_conflict_is_immutable_receipt(self):
        self.save()
        conflict = self.save(key='test-conflict-0002', base=1)
        self.assertEqual((conflict['state'], conflict['revision']), ('conflict', 2))
        self.assertEqual(changes.rule_change_status(self.actor, request_key=conflict['request_key']), conflict)
        unchanged = self.save(key='test-unchanged-0003', base=2)
        self.assertEqual((unchanged['state'], unchanged['revision']), ('unchanged', 2))
        self.assertEqual(self.current()['revision'], 2)

    def test_concurrent_same_key_admits_one_revision(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.save(), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.current()['revision'], 2)
        with self.engine.connect() as conn:
            self.assertEqual(len(conn.execute(select(changes.CHANGES)).all()), 1)

    def test_two_writers_one_conflicts(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda i: self.save(text=f'Rule {i}', key=f'parallel-rule-{i:04d}'), range(2)))
        self.assertEqual({r['state'] for r in results}, {'saved', 'conflict'})
        self.assertEqual(self.current()['revision'], 2)

    def test_restore_appends_and_preserves_all_bytes(self):
        original = self.current()
        self.save()
        restored = changes.restore_rule('restore-history-0001', 'procedures.md', 1, 2, self.actor)
        self.assertEqual((restored['state'], restored['revision']), ('saved', 3))
        self.assertEqual(self.current()['content'], original['content'])
        history = changes.rule_history('procedures.md', 50, self.actor)
        self.assertEqual([row['revision'] for row in history['items']], [3, 2, 1])
        self.assertEqual(changes.read_rules(self.actor, 'procedures.md', 2)['documents'][0]['content'], 'New exact caffè rule\n')
        self.assertEqual(changes.restore_rule('restore-history-0001', 'procedures.md', 1, 2, self.actor), restored)

    def test_rollback_after_publication_failure_keeps_no_receipt_or_revision(self):
        original = projects.write_in_transaction
        def fail_after_write(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('controlled failure before receipt')
        with patch.object(projects, 'write_in_transaction', side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertEqual(self.current()['revision'], 1)
        with self.assertRaises(projects.ProjectError):
            changes.rule_change_status(self.actor, request_key='test-rule-save-0001')
        self.assertEqual(self.save()['revision'], 2)

    def test_nonminter_own_only_and_other_receipts_refused(self):
        result = self.save()
        with patch.dict(os.environ, MEMORY_KEY_SOURCE='shared'):
            self.assertEqual([doc['path'] for doc in changes.read_rules(self.actor)['documents']], [self.path])
            self.assertEqual(self.save(target=self.path, key='own-mailbox-rule-0001')['state'], 'saved')
            for path in ('procedures.md', 'phone.md', 'mail/other@example.test.md'):
                with self.assertRaises(projects.ProjectError):
                    self.save(target=path)
        for other in (replace(self.actor, client_id='foreign-client'), replace(self.actor, grant_id='foreign-grant')):
            with self.assertRaises(projects.ProjectError):
                changes.rule_change_status(other, operation_id=result['operation_id'])
        with self.assertRaises(projects.ProjectError):
            changes.read_rules(replace(self.actor, company_space='foreign'))
        with self.assertRaises(projects.ProjectError):
            changes.read_rules(replace(self.actor, profile_uid='foreign'))

    def test_invalid_utf8_hash_limits_parameters_and_new_paths(self):
        for text in ('', '\ud800', 'x' * 65537):
            with self.assertRaises(projects.ProjectError):
                self.save(text=text)
        for base in (True, 0, '1'):
            with self.assertRaises(projects.ProjectError):
                self.save(base=base)
        for path in ('../procedures.md', 'settings.json', 'mail/new@example.test.md'):
            with self.assertRaises(projects.ProjectError):
                self.save(target=path)
        for limit in (True, 0, 51, '20'):
            with self.assertRaises(projects.ProjectError):
                changes.rule_history(self.path, limit, self.actor)
        with self.engine.begin() as conn:
            conn.execute(update(projects.R).where(projects.key(instructions.PROJECT, 'procedures.md', projects.R)).values(sha256='0' * 64))
        with self.assertRaises(projects.ProjectError):
            self.current()

    def test_legacy_company_cannot_silently_migrate(self):
        with self.engine.begin() as conn:
            conn.execute(update(bindings.MANAGED).values(mode='legacy'))
        for operation in (lambda: changes.read_rules(self.actor), lambda: self.save(),
                          lambda: changes.rule_history(self.path, 20, self.actor)):
            with self.assertRaises(projects.ProjectError):
                operation()
        self.assertNotIn(changes.CHANGES.name, inspect(self.engine).get_table_names())
