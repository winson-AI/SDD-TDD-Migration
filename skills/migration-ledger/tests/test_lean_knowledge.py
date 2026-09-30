"""Real bundled knowledge and target TOML through the managed worker entry."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, check_ref, file_ref, read_json
import knowledge_gate
import lean_worker
import ledger
from lean_tools import foundation_gate, query_knowledge
import test_project_context


class KnowledgeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        prepared = self.f.prepare()
        self.f.start(self.f.init_payload(prepared))
        self.count = 0
        self.journal = (self.f.run / 'ledger/events.jsonl').read_bytes()

    def run_tool(self, operation, args, role='spec-designer'):
        self.count += 1
        result = lean_worker.run(self.f.run, {'request_id': 'knowledge-' + str(self.count),
            'operation': operation, 'args': args}, {'role': role, 'instance_id': role + '-1'})
        self.assertEqual((self.f.run / 'ledger/events.jsonl').read_bytes(), self.journal)
        self.assertTrue(check_ref(result['result_ref']).is_relative_to(self.f.run / 'staging'))
        self.assertEqual(read_json(check_ref(result['receipt_ref']))['status'], 'produced')
        return result, read_json(check_ref(result['result_ref']))

    def resolve(self):
        (self.f.target / 'harmonyApp').mkdir(exist_ok=True)
        return self.run_tool('foundation-resolve', {'requirements': ['Ktor client Curl']})

    def catalog(self, version):
        path = self.f.target / 'gradle/libs.versions.toml'
        path.parent.mkdir(exist_ok=True)
        path.write_text('[versions]\nktor = "' + version + '"\n[libraries]\n'
            'curl = { module = "io.ktor:ktor-client-curl", version.ref = "ktor" }\n')
        return path

    def test_topic_and_foundation_queries_preserve_hash_references(self):
        _, topics = self.run_tool('knowledge-query', {'mode': 'topics'})
        self.assertTrue(any(t['id'] == 'flow-delivery' for t in topics['topics']))
        _, topic = self.run_tool('knowledge-query', {'mode': 'topic', 'topic_id': 'flow-delivery'})
        self.assertIn('StateFlow', topic['content'])
        _, result = self.run_tool('knowledge-query', {'mode': 'foundation', 'query': 'ktor-client-curl'})
        self.assertEqual(result['matches'][0]['coordinate'], 'io.ktor:ktor-client-curl')
        for ref in topic['knowledge_refs'] + result['knowledge_refs']: check_ref(ref)
        self.assertTrue(any(ref['path'].endswith('ktor-client.md') for ref in result['knowledge_refs']))
        self.assertTrue(any(ref['path'].endswith('foundation_api_evidence.json') for ref in result['knowledge_refs']))
        self.assertEqual(list(self.f.target.iterdir()), [])

    def test_diagnosis_reads_real_error_and_never_claims_root_cause(self):
        log = self.f.run / 'build-error.log'
        log.write_text('TLS sessions are not supported on Native platform')
        _, result = self.run_tool('knowledge-diagnose', {'error_ref': file_ref(log)}, 'diagnostician')
        self.assertEqual(result['status'], 'candidates-found')
        self.assertTrue(result['matches'][0]['matched_patterns'])
        self.assertNotIn('quality', result)
        self.assertIn('not a root-cause verdict', result['interpretation'])
        log.write_text('a unique unmatched failure token')
        _, unknown = self.run_tool('knowledge-diagnose', {'error_ref': file_ref(log)}, 'fixer')
        self.assertEqual(unknown['status'], 'no-match')
        self.assertEqual(unknown['matches'], [])

    def test_external_query_preserves_complete_refs_without_probe_or_install(self):
        with patch('subprocess.run', side_effect=AssertionError('knowledge must not execute commands')):
            _, result = self.run_tool('knowledge-query', {'mode': 'external', 'query': 'webrtc'})
        self.assertEqual(result['status'], 'candidates-found')
        item, = result['matches']
        self.assertEqual(item['id'], 'ohos-webrtc')
        self.assertIsNone(item['probe'])
        self.assertEqual(item['probe_support']['status'], 'not-supported')
        self.assertIn('not-executed', item['execution'])
        self.assertIn('not executed', result['verification'])
        refs = {ref['path'] for ref in result['knowledge_refs']}
        self.assertIn(item['record_path'], refs)
        self.assertIn(item['cookbook_path'], refs)
        self.assertIn(result['sdd_adaptation_ref']['path'], refs)
        for ref in result['knowledge_refs']: check_ref(ref)
        self.assertIn('not_yet_proven', read_json(Path(item['record_path'])))
        self.assertEqual(list(self.f.target.iterdir()), [])
        self.assertFalse((self.f.run / '.a2c').exists())
        _, unknown = self.run_tool('knowledge-query', {'mode': 'external', 'query': 'no-such-capability-123'})
        self.assertEqual(unknown['status'], 'no-match')
        self.assertEqual(unknown['matches'], [])

    def test_external_catalog_rejects_missing_escaping_or_executable_refs(self):
        original = query_knowledge._load_json
        cases = [
            ('record', 'missing.json', 'missing'),
            ('cookbook', '/etc/passwd', 'escapes root'),
            ('record', '../foundation-api-knowledge/index.json', 'escapes root'),
            ('probe', 'scripts/probe_ohos_webrtc.py', 'not supported'),
        ]
        for key, value, message in cases:
            def changed(path):
                data = original(path)
                if Path(path).parent.name == 'external-capabilities' and Path(path).name == 'index.json':
                    data['entries'][0][key] = value
                return data
            with self.subTest(key=key, value=value), patch.object(query_knowledge, '_load_json', side_effect=changed):
                with self.assertRaisesRegex(Rejected, message):
                    self.run_tool('knowledge-query', {'mode': 'external', 'query': 'webrtc'})

    def test_knowledge_adaptation_is_indexed_and_transient_rule_is_explicit(self):
        _, result = self.run_tool('knowledge-query', {'mode': 'topic', 'topic_id': 'sdd-knowledge-adaptation'})
        self.assertIn('.sdd-runs/<run_id>', result['content'])
        self.assertIn('frozen OpenSpec', result['content'])
        _, result = self.run_tool('knowledge-query', {'mode': 'topic', 'topic_id': 'ui-screenshot-determinism'})
        self.assertIn('Do not add fake delay', result['content'])
        self.assertIn('state-transition/semantic assertions', result['content'])
        self.assertNotIn('Capture meaningful states such as loading', result['content'])

    def test_resolve_then_verify_actual_target_catalog_and_reject_mismatch(self):
        receipt, resolution = self.resolve()
        self.assertEqual(resolution['status'], 'passed')
        knowledge_gate.validate_resolution(receipt['result_ref'])
        catalog = self.catalog(resolution['requirements'][0]['version'])
        with catalog.open('a') as out:
            out.write('unrelated = { module = "example:unrelated", version.ref = "defined-elsewhere" }\n')
        before = catalog.read_bytes()
        _, checked = self.run_tool('foundation-verify', {
            'resolution_ref': receipt['result_ref'], 'catalog_ref': file_ref(catalog)}, 'test-runner')
        self.assertEqual(checked['status'], 'foundation-verified')
        self.assertEqual(catalog.read_bytes(), before)
        self.assertIn('runtime remain unverified', checked['verification'])
        self.catalog('wrong-version')
        with self.assertRaisesRegex(Rejected, 'version verification failed'):
            self.run_tool('foundation-verify', {
                'resolution_ref': receipt['result_ref'], 'catalog_ref': file_ref(catalog)}, 'test-runner')
        failed = self.f.run / 'staging/test-runner-1' / ('knowledge-' + str(self.count)) / 'receipt.json'
        self.assertEqual(read_json(failed)['status'], 'rejected')
        self.assertEqual((self.f.run / 'ledger/events.jsonl').read_bytes(), self.journal)

    def test_catalog_conflicting_aliases_are_rejected(self):
        receipt, resolved = self.resolve()
        catalog = self.catalog(resolved['requirements'][0]['version'])
        with catalog.open('a') as out:
            out.write('duplicate = { module = "io.ktor:ktor-client-curl", version = "wrong" }\n')
        with self.assertRaisesRegex(Rejected, 'conflicting versions'):
            self.run_tool('foundation-verify', {
                'resolution_ref': receipt['result_ref'], 'catalog_ref': file_ref(catalog)}, 'fixer')

    def test_self_reported_resolution_cannot_invent_catalog_version(self):
        receipt, resolved = self.resolve()
        resolved['requirements'][0]['version'] = '99.99.99-not-in-bundle'
        resolved['requirements'][0]['gav'] = 'io.ktor:ktor-client-curl:99.99.99-not-in-bundle'
        forged = self.f.run / 'staging/forged-resolution.json'
        forged.write_text(json.dumps(resolved))
        catalog = self.catalog('99.99.99-not-in-bundle')
        with self.assertRaisesRegex(Rejected, 'differs from its Foundation catalog'):
            self.run_tool('foundation-verify', {'resolution_ref': file_ref(forged),
                'catalog_ref': file_ref(catalog)}, 'test-runner')

    def test_scope_roles_and_ambiguous_requirements_fail_with_receipts(self):
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_tool('foundation-resolve', {'requirements': ['Ktor client Curl']}, 'fixer')
        (self.f.target / 'harmonyApp').mkdir()
        with self.assertRaisesRegex(Rejected, 'exactly one'):
            self.run_tool('foundation-resolve', {'requirements': ['Ktor']})
        receipt, resolved = self.resolve()
        outside = self.f.base / 'libs.versions.toml'; outside.write_bytes(self.catalog(resolved['requirements'][0]['version']).read_bytes())
        with self.assertRaisesRegex(Rejected, 'inside target root'):
            self.run_tool('foundation-verify', {'resolution_ref': receipt['result_ref'],
                'catalog_ref': file_ref(outside)}, 'auditor')
        other = self.f.base / 'other-resolution.json'; other.write_bytes(check_ref(receipt['result_ref']).read_bytes())
        with self.assertRaisesRegex(Rejected, 'belong to this run'):
            self.run_tool('foundation-verify', {'resolution_ref': file_ref(other),
                'catalog_ref': file_ref(self.catalog(resolved['requirements'][0]['version']))}, 'auditor')
        link = self.f.run / 'staging/outside-resolution.json'; link.symlink_to(other)
        # Preserve attacker spelling: file_ref normalizes it and would hide this boundary case.
        for alias in (link, self.f.run / '../../other-resolution.json'):
            with self.subTest(alias=alias), self.assertRaisesRegex(Rejected, 'belong to this run'):
                self.run_tool('foundation-verify', {'resolution_ref': {
                    'path': str(alias), 'sha256': file_ref(other)['sha256']},
                    'catalog_ref': file_ref(self.catalog(resolved['requirements'][0]['version']))}, 'auditor')

    def test_non_harmony_and_no_new_dependencies_are_explicit(self):
        _, result = self.run_tool('foundation-resolve', {'requirements': [], 'no_new_dependencies': True})
        self.assertEqual(result['status'], 'not_required_non_harmony_target')
        (self.f.target / 'harmonyApp').mkdir()
        output, result = self.run_tool('foundation-resolve', {'requirements': [], 'no_new_dependencies': True})
        self.assertEqual(result['status'], 'not_required_no_new_dependencies')
        knowledge_gate.validate_resolution(output['result_ref'])
        self.assertEqual([p.name for p in self.f.target.iterdir()], ['harmonyApp'])

    def test_target_detection_ignores_retained_artifacts_and_symlink_projects(self):
        old = self.f.target / '.sdd-runs/old/ohosMain'; old.mkdir(parents=True)
        elsewhere = self.f.base / 'other/harmonyApp'; elsewhere.mkdir(parents=True)
        (self.f.target / 'shared').symlink_to(elsewhere.parent, target_is_directory=True)
        self.assertFalse(foundation_gate._target_has_ohos(self.f.target))
        (self.f.target / 'build.gradle.kts').write_text('kotlin { ohosArm64() }')
        self.assertTrue(foundation_gate._target_has_ohos(self.f.target))


if __name__ == '__main__':
    unittest.main()
