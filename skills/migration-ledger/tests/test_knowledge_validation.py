"""Foundation resolution gate and external validation-result -> three-state / HAP artifact mapping."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import knowledge_gate
import lean_adapter
from contracts import Rejected, file_ref


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def ref(self, name, content):
        p = self.base / name
        p.write_text(content if isinstance(content, str) else json.dumps(content))
        return file_ref(p)


class KnowledgeGateTests(Base):
    def resolution(self, **over):
        item = {'query': 'io.example:core', 'resolved_version': '1.2.3', 'subclosure': ['Client.get']}
        item.update(over)
        return {'schema_version': 1, 'requirements': [item]}

    def test_valid_resolution(self):
        knowledge_gate.validate_resolution(self.ref('r.json', self.resolution()))

    def test_requirements_need_exact_version(self):
        with self.assertRaisesRegex(Rejected, 'resolved_version'):
            knowledge_gate.validate_resolution(self.ref('r2.json', self.resolution(resolved_version=None)))

    def test_demo_source_is_candidate_only(self):
        with self.assertRaisesRegex(Rejected, 'candidate configuration'):
            knowledge_gate.validate_resolution(self.ref('r3.json', self.resolution(evidence='demo-source')))
        knowledge_gate.validate_resolution(self.ref('r4.json', self.resolution(evidence='demo-source', candidate_only=True)))

    def test_freeze_gate_flag(self):
        m = {'module_id': 'M001', 'plan': {}}
        knowledge_gate.freeze_gate({}, m)  # off -> no-op
        with self.assertRaisesRegex(Rejected, 'must bind a foundation resolution'):
            knowledge_gate.freeze_gate({'dependency_resolution_required': True}, m)
        m['plan']['dependency_resolution_ref'] = self.ref('r5.json', self.resolution())
        with self.assertRaisesRegex(Rejected, 'bundled Foundation catalog'):  # hand-written, not managed
            knowledge_gate.freeze_gate({'dependency_resolution_required': True}, m)
        import lean_knowledge
        target = self.base / 'target'; target.mkdir()
        managed = lean_knowledge.run('foundation-resolve', {'requirements': [], 'no_new_dependencies': True},
                                     {'target_root': str(target)}, self.base)
        m['plan']['dependency_resolution_ref'] = self.ref('r6.json', managed)
        knowledge_gate.freeze_gate({'dependency_resolution_required': True, 'target_root': str(target)}, m)


class ValidationSummaryTests(Base):
    def result(self, **over):
        base = {'verdict': 'BUILD_READY',
                'checks': [{'kind': 'compile', 'status': 'passed'}, {'kind': 'test', 'status': 'passed'}]}
        base.update(over)
        return base

    def test_all_passed_is_green(self):
        out = lean_adapter.validation_summary(self.result())
        self.assertEqual((out['quality'], out['failed_checks']), ('green-passed', []))

    def test_any_failure_is_red(self):
        out = lean_adapter.validation_summary(self.result(
            checks=[{'kind': 'compile', 'status': 'passed'}, {'kind': 'test', 'status': 'failed'}]))
        self.assertEqual((out['quality'], out['failed_checks']), ('red-bug', ['test']))

    def test_package_check_requires_artifact(self):
        packaged = self.result(checks=[{'kind': 'package', 'status': 'passed'}])
        with self.assertRaisesRegex(Rejected, 'built artifact'):
            lean_adapter.validation_summary(packaged)
        hap = self.ref('app.hap', 'binary-ish')
        out = lean_adapter.validation_summary({**packaged, 'artifacts': [hap]})
        self.assertEqual(len(out['artifacts']), 1)

    def test_artifact_hash_must_still_match(self):
        hap = self.ref('app2.hap', 'v1')
        (self.base / 'app2.hap').write_text('DRIFTED')
        with self.assertRaises((Rejected, ValueError)):
            lean_adapter.validation_summary({**self.result(checks=[{'kind': 'package', 'status': 'passed'}]),
                                             'artifacts': [hap]})

    def test_check_status_and_kind_required(self):
        with self.assertRaisesRegex(Rejected, 'needs a kind'):
            lean_adapter.validation_summary(self.result(checks=[{'status': 'passed'}]))
        with self.assertRaisesRegex(Rejected, 'passed/failed'):
            lean_adapter.validation_summary(self.result(checks=[{'kind': 'compile', 'status': 'ok'}]))


if __name__ == '__main__':
    unittest.main()
