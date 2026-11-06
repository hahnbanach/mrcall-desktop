import base64
import hashlib
import json
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select, insert, update, inspect

from zylch.services import operator_instructions as instructions
from zylch.services import operator_rule_proposals as rules
from zylch.services import project_store as projects
from zylch.storage.models import ProjectSpace


class RuleProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + self.tmp.name + '/company.db', connect_args={'timeout': 10})
        for table in (projects.S, projects.D, projects.R):
            table.create(self.engine)
        with self.engine.begin() as conn:
            conn.execute(insert(ProjectSpace.__table__).values(id=1, space_id='company-a'))
        self.patches = [patch('zylch.storage.database.current_memory_engine', return_value=self.engine),
            patch.dict(os.environ, OWNER_ID='uid-a', EMAIL_ADDRESS='owner@example.test', MEMORY_KEY_SOURCE='mint')]
        for item in self.patches:
            item.start()
        self.actor = rules.trusted_mcp_binding(profile_uid='uid-a', company_space='company-a',
            mailbox='owner@example.test', client_id='client-a', grant_id='grant-a')
        self.human = rules.trusted_native_binding(profile_uid='uid-a', company_space='company-a', mailbox='owner@example.test')
        self.path = instructions.mail_path(self.actor.mailbox)
        for path, text in ((instructions.PROCEDURES, 'Company procedures'), (self.path, 'Mailbox identity'), ('phone.md', 'Company procedures'), ('mail/other@example.test.md', 'Other identity')):
            instructions.store('company-a', path, base64.b64encode(text.encode()).decode(), 0, self.actor.mailbox)
        rules.configure_import_proof(None)

    def tearDown(self):
        rules.configure_import_proof(None)
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.tmp.cleanup()

    def proof(self):
        from cs.operator_import import build_proof
        root = Path(self.tmp.name) / 'clone'
        (root / 'company/mailboxes').mkdir(parents=True, exist_ok=True)
        (root / 'manifest.toml').write_text('[operator]\nemail_address="owner@example.test"\n')
        (root / 'company/customer-service-playbook.md').write_text('Company procedures')
        (root / 'company/mailbox-identity.md').write_text('Mailbox identity')
        (root / 'company/mailboxes/other@example.test.md').write_text('Other identity')
        published = [projects.read(instructions.PROJECT, path) for path in
            (instructions.PROCEDURES, self.path, 'phone.md', 'mail/other@example.test.md')]
        return build_proof(root, profile_uid='uid-a', space_id='company-a',
                           mailbox=self.actor.mailbox, published_documents=published)

    def import_managed(self, proof=None, expected_digest=None):
        proof = proof or self.proof()
        path = Path(self.tmp.name) / 'import.json'
        if os.geteuid() == 0:
            from cs.operator_import import write_proof
            path.unlink(missing_ok=True)
            write_proof(path, proof, tenant_gid=os.getgid())
        else:
            path.write_text(json.dumps(proof))
            path.chmod(0o640)
        rules.configure_import_proof(str(path))
        real_fstat = os.fstat
        def protected(fd):
            value = real_fstat(fd)
            return os.stat_result((value.st_mode, value.st_ino, value.st_dev, value.st_nlink,
                                   0, value.st_gid, value.st_size, value.st_atime, value.st_mtime, value.st_ctime))
        if os.geteuid() == 0:
            view = rules.preview_import(self.human)
            return rules.confirm_import(expected_digest or view['digest'], self.human)
        with patch.object(rules.os, 'fstat', side_effect=protected):
            view = rules.preview_import(self.human)
            return rules.confirm_import(expected_digest or view['digest'], self.human)

    def test_published_preview_needs_no_proof_and_does_not_change_rules(self):
        tables_before = set(inspect(self.engine).get_table_names())
        before = [projects.read(instructions.PROJECT, path) for path in
                  (instructions.PROCEDURES, self.path, 'phone.md', 'mail/other@example.test.md')]
        preview = rules.preview_import(self.human)
        self.assertEqual({doc['path'] for doc in preview['documents']}, {doc['path'] for doc in before})
        self.assertEqual(preview['mode'], 'legacy')
        self.assertGreater(preview['expires_at'], time.time())
        self.assertEqual(set(inspect(self.engine).get_table_names()), tables_before)
        with self.assertRaises(projects.ProjectError):
            rules.confirm_import(preview['digest'], self.human)
        self.assertEqual(before, [projects.read(instructions.PROJECT, doc['path']) for doc in before])
        with projects.connection('company-a') as (conn, space):
            self.assertFalse(rules.managed_in_transaction(conn, space))

    def test_renewed_proof_preserves_exact_reviewed_semantic_digest(self):
        reviewed = rules.preview_import(self.human)
        proof = self.proof()
        first = self.import_managed(proof, expected_digest=reviewed['digest'])
        proof['created_at'] -= 1
        proof['expires_at'] -= 1
        renewed = self.import_managed(proof, expected_digest=reviewed['digest'])
        self.assertNotEqual(first['proof_sha256'], renewed['proof_sha256'])
        self.assertEqual(first['digest'], reviewed['digest'])
        self.assertEqual(renewed['digest'], reviewed['digest'])

    def test_expired_proof_does_not_hide_published_preview_or_authorize_cutover(self):
        proof = self.proof()
        proof['created_at'] -= 1000
        proof['expires_at'] -= 1000
        reviewed = rules.preview_import(self.human)
        with self.assertRaises(projects.ProjectError):
            self.import_managed(proof, expected_digest=reviewed['digest'])
        self.assertEqual(rules.preview_import(self.human)['digest'], reviewed['digest'])
        with projects.connection('company-a') as (conn, space):
            self.assertFalse(rules.managed_in_transaction(conn, space))

    def test_changed_published_text_revision_and_owner_change_review_digest(self):
        reviewed = rules.preview_import(self.human)
        instructions.store('company-a', instructions.PROCEDURES,
                           base64.b64encode(b'Changed exact published rule').decode(), 1, self.actor.mailbox)
        updated = rules.preview_import(self.human)
        self.assertNotEqual(updated['digest'], reviewed['digest'])
        self.assertEqual(next(doc for doc in updated['documents'] if doc['path'] == instructions.PROCEDURES)['revision'], 2)
        other = rules.trusted_native_binding(profile_uid='another-profile', company_space='company-a', mailbox='owner@example.test')
        with self.assertRaises(projects.ProjectError):
            rules.preview_import(other)
        with patch.dict(os.environ, OWNER_ID='another-profile'):
            self.assertNotEqual(rules.preview_import(other)['digest'], updated['digest'])

    def propose(self, text='A new rule', base=1):
        return rules.propose(instructions.PROCEDURES, text, base, self.actor)

    def test_legacy_compatibility_and_explicit_cutover(self):
        proposal = self.propose()
        with self.assertRaises(projects.ProjectError):
            rules.decide(proposal['id'], proposal['digest'], 'confirm', self.human)
        self.assertEqual(rules.status(proposal['id'], self.actor)['state'], 'pending')
        imported = self.import_managed()
        self.assertEqual(imported['mode'], 'managed')
        result = rules.decide(proposal['id'], proposal['digest'], 'confirm', self.human)
        self.assertEqual((result['state'], result['published_revision']), ('confirmed', 2))
        self.assertEqual(projects.read(instructions.PROJECT, instructions.PROCEDURES)['sha256'], result['published_sha256'])
        with self.assertRaises(projects.ProjectError):
            instructions.store('company-a', instructions.PROCEDURES, base64.b64encode(b'Legacy overwrite').decode(), 2, 'owner')

    def test_preview_reports_authority_and_current_confirmed_revision(self):
        before = instructions.preview()
        self.assertEqual(before['authority'], 'legacy')
        self.assertEqual(before['space_id'], 'company-a')
        self.assertEqual({doc['path'] for doc in before['documents']},
                         {self.path, instructions.PROCEDURES})
        self.import_managed()
        managed = instructions.preview()
        self.assertEqual(managed['authority'], 'managed')
        self.assertEqual(managed['documents'], before['documents'])
        text = 'A confirmed rule with exact accents: caffè\n'
        proposal = self.propose(text)
        rules.decide(proposal['id'], proposal['digest'], 'confirm', self.human)
        after = instructions.preview()
        document = next(doc for doc in after['documents']
                        if doc['path'] == instructions.PROCEDURES)
        self.assertEqual(after['authority'], 'managed')
        self.assertEqual(document['revision'], 2)
        self.assertEqual(base64.b64decode(document['content_base64']).decode(), text)
        self.assertEqual(document['sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertIn(text, after['block'])

    def test_forged_human_foreign_space_targets_and_grant(self):
        proposal = self.propose()
        forged = rules.HumanBinding('uid-a', 'company-a', self.actor.mailbox, 'desktop', 'native-owner')
        for actor in (forged, self.actor, {'human': True}):
            with self.assertRaises(projects.ProjectError):
                rules.decide(proposal['id'], proposal['digest'], 'confirm', actor)
        for path in ('phone.md', 'mail/other@example.test.md', '../procedures.md'):
            with self.assertRaises(projects.ProjectError):
                rules.propose(path, 'x', 1, self.actor)
        foreign = rules.trusted_mcp_binding(profile_uid='uid-a', company_space='foreign', mailbox=self.actor.mailbox,
                                           client_id='client-a', grant_id='grant-a')
        with self.assertRaises(projects.ProjectError):
            rules.propose(instructions.PROCEDURES, 'x', 1, foreign)
        other_grant = rules.trusted_mcp_binding(profile_uid='uid-a', company_space='company-a', mailbox=self.actor.mailbox,
                                              client_id='client-a', grant_id='other')
        with self.assertRaises(projects.ProjectError):
            rules.status(proposal['id'], other_grant)

    def test_idempotency_reject_expire_and_current_rights(self):
        first = self.propose()
        self.assertEqual(self.propose()['id'], first['id'])
        self.assertEqual(len(rules.list_pending(self.human)['items']), 1)
        rejected = rules.decide(first['id'], first['digest'], 'reject', self.human)
        self.assertEqual(rejected['state'], 'rejected')
        second = self.propose('Second rule')
        with patch.object(rules.time, 'time', return_value=second['expires_at']+1):
            self.assertEqual(rules.status(second['id'], self.actor)['state'], 'expired')
        self.import_managed()
        third = self.propose('Third rule')
        with patch.dict(os.environ, MEMORY_KEY_SOURCE='provision'):
            with self.assertRaises(projects.ProjectError):
                rules.decide(third['id'], third['digest'], 'confirm', self.human)
        with patch.dict(os.environ, OWNER_ID='other'):
            with self.assertRaises(projects.ProjectError):
                rules.status(third['id'], self.actor)

    def test_identical_content_stale_revision_is_conflict(self):
        self.import_managed()
        stale = self.propose('Company procedures', base=0)
        result = rules.decide(stale['id'], stale['digest'], 'confirm', self.human)
        self.assertEqual(result['state'], 'conflict')
        with projects.connection('company-a', write=True) as (conn, space):
            with self.assertRaises(projects.ProjectError):
                projects.write_in_transaction(conn, space, instructions.PROJECT, instructions.PROCEDURES,
                                              b'Company procedures', 0, 'owner')

    def test_transaction_rollback_leaves_pending_and_original_revision(self):
        self.import_managed()
        proposal = self.propose()
        actual_append = projects.append
        def fail_after_write(*args, **kwargs):
            actual_append(*args, **kwargs)
            raise RuntimeError('controlled transaction failure')
        with patch.object(projects, 'append', side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                rules.decide(proposal['id'], proposal['digest'], 'confirm', self.human)
        self.assertEqual(rules.status(proposal['id'], self.actor)['state'], 'pending')
        self.assertEqual(projects.read(instructions.PROJECT, instructions.PROCEDURES)['revision'], 1)

    def test_concurrent_decisions_publish_once(self):
        self.import_managed()
        proposal = self.propose()
        def confirm(_):
            return rules.decide(proposal['id'], proposal['digest'], 'confirm', self.human)['state']
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(confirm, range(2))), ['confirmed', 'confirmed'])
        with self.engine.connect() as conn:
            self.assertEqual(len(conn.execute(select(projects.R).where(projects.R.c.path == instructions.PROCEDURES)).all()), 2)

    def test_concurrent_different_proposals_conflict_without_overwrite(self):
        self.import_managed()
        proposals = [self.propose('First changed rule'), self.propose('Second changed rule')]
        def confirm(proposal):
            return rules.decide(proposal['id'], proposal['digest'], 'confirm', self.human)['state']
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(confirm, proposals)), ['confirmed', 'conflict'])
        self.assertEqual(projects.read(instructions.PROJECT, instructions.PROCEDURES)['revision'], 2)

    def test_import_rejects_full_snapshot_mismatch_stale_and_unknown(self):
        for change in ('missing', 'content', 'source', 'expired'):
            proof = self.proof()
            if change == 'missing':
                proof['documents'].pop()
            elif change == 'content':
                doc = proof['documents'][0]
                doc['content_base64'] = base64.b64encode(b'Unpublished clone instruction').decode()
                doc['sha256'] = doc['base_sha256'] = hashlib.sha256(b'Unpublished clone instruction').hexdigest()
            elif change == 'source':
                proof['source_files'] = {}
            else:
                proof['created_at'] -= 1000
                proof['expires_at'] -= 1000
            with self.assertRaises(projects.ProjectError):
                self.import_managed(proof)
        with projects.connection('company-a') as (conn, space):
            self.assertFalse(rules.managed_in_transaction(conn, space))

    def test_full_compiler_import_preserves_phone_and_other_identity(self):
        proof = self.proof()
        self.assertEqual(set(proof['compiled_paths']),
            {instructions.PROCEDURES, self.path, 'phone.md', 'mail/other@example.test.md'})
        self.assertIn('manifest.toml', proof['source_files'])
        imported = self.import_managed(proof)
        self.assertEqual(len(imported['documents']), 4)
        self.assertEqual(projects.read(instructions.PROJECT, 'phone.md')['revision'], 1)
        self.assertEqual(projects.read(instructions.PROJECT, 'mail/other@example.test.md')['revision'], 1)

    def test_compiler_producer_refuses_dirty_sources_and_extra_published_paths(self):
        from cs.operator_import import build_proof
        self.proof()
        root = Path(self.tmp.name) / 'clone'
        published = [projects.read(instructions.PROJECT, path) for path in
            (instructions.PROCEDURES, self.path, 'phone.md', 'mail/other@example.test.md')]
        (root / 'company/customer-service-playbook.md').write_text('Unpublished local changes')
        with self.assertRaises(ValueError):
            build_proof(root, profile_uid='uid-a', space_id='company-a',
                        mailbox=self.actor.mailbox, published_documents=published)
        self.proof()
        with self.assertRaises(ValueError):
            build_proof(root, profile_uid='uid-a', space_id='company-a',
                        mailbox=self.actor.mailbox, published_documents=published[:-1])
        proof = self.proof()
        proof['documents'] = [d for d in proof['documents'] if d['path'] != 'phone.md']
        proof['compiled_paths'].remove('phone.md')
        with self.assertRaises(projects.ProjectError):
            self.import_managed(proof)

    def test_proof_permissions_and_digest_changes_refuse(self):
        path = Path(self.tmp.name) / 'proof.json'
        path.write_text(json.dumps(self.proof()))
        path.chmod(0o666)
        rules.configure_import_proof(str(path))
        published = rules.preview_import(self.human)
        with self.assertRaises(projects.ProjectError):
            rules.confirm_import(published['digest'], self.human)
        self.import_managed()
        proposal = self.propose()
        with self.assertRaises(projects.ProjectError):
            rules.decide(proposal['id'], '0'*64, 'confirm', self.human)
        for value in ('', '\ud800', 'x'*65537):
            with self.assertRaises(projects.ProjectError):
                self.propose(value)


if __name__ == '__main__':
    unittest.main()
