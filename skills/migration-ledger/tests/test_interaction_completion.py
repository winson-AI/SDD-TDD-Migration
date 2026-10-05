"""Native Harmony reports without gesture proof close as evidence-limited Yellow."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_automation_interactions
import execute_test
from contracts import Rejected, check_ref, read_json, validate_result

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
import harmony_stage


class InteractionCompletionTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_automation_interactions.AutomationInteractionTests()
        f.setUp(); self.addCleanup(f.doCleanups)
        f.path.update(name='settings edge back', steps=['Open settings/base', 'Swipe from the edge to exit'],
            expected_assertions=[{'assertion_id': 'A-BACK', 'expected': True, 'description': 'App left foreground',
                                  'verification': 'video_assert', 'matcher': 'exact', 'after_step': 2}])
        f.module['plan'].update(module_id='M001', definitions=[], tasks=[])
        f.module['stale'] = False
        self.assignment = {'run_id': 'gesture', 'module_id': 'M001', 'assignment_id': 'AUTO',
                           'role': 'test-runner', 'instance_id': 'runner', 'closed': False}
        f.module['assignments'] = {'AUTO': self.assignment}
        self.state = {'run_id': 'gesture', 'modules': {'M001': f.module}}

    def run_report(self, passed):
        f = self.f
        scripts = str(Path(__file__).resolve().parents[2] / 'migration-test/scripts')
        fixtures = str(Path(__file__).resolve().parent)
        adapter = f.f.n.write('.sdd-runs/gesture/staging/native-report.py', f'''
import json, sys
from pathlib import Path
sys.path.insert(0, {scripts!r})
sys.path.insert(0, {fixtures!r})
from test_harmony_integration import step_evidence
from harmony_contract import ObservationSink, validate_query, write
q = json.loads(Path(sys.argv[sys.argv.index('--query-file') + 1]).read_text())
out = Path(sys.argv[sys.argv.index('--result-file') + 1])
validate_query(q)
media = out.parent / 'video-evidence.txt'; media.write_text('fixture for recorded observation')
sink = ObservationSink(q, out.parent)
sink.record('[ASSERT:A-BACK]', {passed!r}, 'observed fixture outcome', 'video_assert', [media])
report = sink.report()
proof = out.parent / 'completed-steps'; proof.mkdir()
report.update(step_evidence(q, proof, {passed!r}))
write(out, report)
sys.exit(0 if report['quality'] == 'green-passed' else 1)
''')
        with patch.object(execute_test, 'status', return_value=self.state):
            receipt_ref = execute_test.execute(f.run, 'M001', 'AUTO', f.path['path_id'],
                [sys.executable, '-B', str(adapter)], f.f.n.target,
                f.run / 'runs/harmony/automation/attempt', timeout=10)
        receipt = read_json(check_ref(receipt_ref))
        native = read_json(check_ref(receipt['result_ref']))
        with patch.object(harmony_stage, 'status', return_value=self.state):
            stage = harmony_stage.build(f.run, 'M001', 'AUTO', [receipt_ref])
        self.assertEqual(validate_result(stage, f.module, self.assignment, run_root=f.run), 'tests')
        return native, stage

    def test_native_green_without_interaction_proof_accepts_as_executed_yellow(self):
        native, stage = self.run_report(True)
        row = stage['paths'][0]
        self.assertEqual(native['quality'], 'green-passed')
        self.assertEqual(row['quality'], 'yellow-blocked')
        self.assertIs(row['executed'], True)
        self.assertEqual(row['root_cause']['reason_code'], 'interaction-evidence-unavailable')
        self.assertEqual(row['assertions'], native['assertions'])
        self.assertNotIn('interaction_evidence', row)
        self.assertIn(native['observations_ref'], row['root_cause']['evidence_refs'])
        observations = read_json(check_ref(native['observations_ref']))
        self.assertTrue(observations[0]['evidence_refs'])
        for ref in observations[0]['evidence_refs']:
            check_ref(ref)
        forged = copy.deepcopy(stage); forged['paths'][0]['quality'] = 'green-passed'
        with self.assertRaisesRegex(Rejected, 'host completion interpretation changed'):
            validate_result(forged, self.f.module, self.assignment, run_root=self.f.run)

    def test_native_red_stays_red_without_interaction_proof(self):
        native, stage = self.run_report(False)
        row = stage['paths'][0]
        self.assertEqual(row['quality'], 'red-bug')
        self.assertIs(row['executed'], True)
        self.assertEqual(row['root_cause'], native['root_cause'])
        self.assertEqual(row['assertions'], native['assertions'])
        self.assertIs(row['assertions'][0]['actual'], False)
