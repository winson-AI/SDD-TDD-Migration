"""Managed visual tools retain the existing build, assignment and audit boundaries."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, baseline, check_ref, file_ref, read_json, verify_plan
import lean_worker
import ledger
import test_project_context


class VisualDispatchTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.start(self.f.init_payload(self.f.prepare()))
        self.state, self.events = ledger.read_events(self.f.run)
        self.journal = (self.f.run / 'ledger/events.jsonl').read_bytes()
        self.actor = {'role': 'test-runner', 'instance_id': 'runner'}
        self.task = {'assignment_id': 'V1', 'role': 'test-runner', 'instance_id': 'runner',
                     'test_scope': 'automation', 'fencing_token': 8, 'freeze_id': 'F1', 'closed': False,
                     'execution_contract': {'task_ids': [], 'path_ids': ['PB', 'PA', 'PV']}}
        code = self.ref(self.f.target / 'Main.kt', 'fun main() = Unit')
        current = baseline([code])
        selection = self.ref(self.f.run / 'staging/selection.md', 'current frozen build')
        image = self.ref(self.f.run / 'staging/reference.png', 'image fixture')
        self.module = {'module_id': 'M001', 'phase': 'testing', 'freeze_id': 'F1',
                       'code_files': [code], 'code_baseline': current, 'build_baseline': current,
                       'assignments': {'V1': self.task}, 'stale': False,
                       'plan': {'definitions': [], 'paths': [
                           {'path_id': 'PB', 'kind': 'build', 'command': {'selection_ref': selection}},
                           {'path_id': 'PA', 'kind': 'automation'},
                           {'path_id': 'PV', 'kind': 'visual', 'coverage': 'home:content:viewport',
                            'node_ids': ['node:root'], 'baseline_ref': image}]},
                       'results': {'PB': {'quality': 'green-passed', 'code_baseline': current}}}
        self.state['modules'] = {'M001': self.module}
        self.count = 0

    def ref(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        return file_ref(path)

    def request(self, operation='visual-install'):
        self.count += 1
        return {'request_id': 'visual-' + str(self.count), 'operation': operation,
                'module_id': 'M001', 'assignment_id': 'V1', 'fencing_token': 8,
                'args': {'path_id': 'PA' if operation == 'visual-install' else 'PV'}}

    def invoke(self, request):
        with patch.object(ledger, 'read_events', return_value=(self.state, self.events)):
            return lean_worker.run(self.f.run, request, self.actor)

    def test_install_can_prepare_automation_but_cannot_skip_failed_build(self):
        self.module['results']['PB']['quality'] = 'red-bug'
        with self.assertRaisesRegex(Rejected, 'build must pass'):
            self.invoke(self.request())
        self.module['results']['PB']['quality'] = 'green-passed'
        # Missing optional capture configuration yields real managed Yellow evidence,
        # without a device call, automatic acceptance or rewriting the journal.
        before = copy.deepcopy(self.state)
        output = self.invoke(self.request())
        result = read_json(check_ref(output['result_ref']))
        self.assertEqual(result['quality_candidate'], 'yellow-blocked')
        self.assertFalse(result['executed'])
        attempt = check_ref(output['receipt_ref']).parent
        self.assertTrue(attempt.is_relative_to(self.f.run / 'runs/harmony/sandbox/runner'))
        self.assertEqual(read_json(attempt / 'cleanup.json')['status'], 'removed')
        self.assertEqual(self.state, before)
        self.assertEqual((self.f.run / 'ledger/events.jsonl').read_bytes(), self.journal)

    def test_capture_and_semantics_wait_for_functional_green(self):
        self.task['test_scope'] = 'visual'
        for operation in ('visual-capture', 'semantic-inspect'):
            with self.subTest(operation=operation), self.assertRaisesRegex(Rejected, 'functional layer'):
                self.invoke(self.request(operation))
        self.module['results']['PA'] = {'quality': 'green-passed', 'code_baseline': self.module['code_baseline']}
        output = self.invoke(self.request('visual-capture'))
        self.assertEqual(read_json(check_ref(output['result_ref']))['status'], 'BLOCKED')

    def test_no_resource_or_source_authority_is_granted(self):
        self.actor['role'] = 'implementer'
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.invoke(self.request())
        self.actor['role'] = 'test-runner'
        request = self.request(); request['fencing_token'] = 7
        with self.assertRaisesRegex(Rejected, 'stale fencing token'):
            self.invoke(request)
        self.task['closed'] = True
        with self.assertRaisesRegex(Rejected, 'active assignment'):
            self.invoke(self.request())

    def test_visual_environment_hash_remains_part_of_frozen_plan(self):
        env = self.ref(self.f.run / 'runs/harmony/sandbox/environment/visual.json', '{}')
        self.module['plan']['paths'][1]['visual_execution'] = {'environment_ref': env}
        verify_plan(self.module['plan'])
        Path(env['path']).write_text('{"changed": true}')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            verify_plan(self.module['plan'])

    def test_stale_audit_snapshot_cannot_execute_domain_tools(self):
        self.state['global_paths'] = []
        self.state['audit_assignment'] = {'assignment_id': 'A1', 'role': 'auditor', 'instance_id': 'auditor',
            'closed': False, 'scope_policy': 'non-green-only', 'path_ids': ['PV'], 'snapshot': {'M001': 'old'}}
        self.actor = {'role': 'auditor', 'instance_id': 'auditor'}
        request = self.request('visual-capture')
        request.update(module_id='GLOBAL', assignment_id='A1', fencing_token=None)
        with self.assertRaisesRegex(Rejected, 'current global audit snapshot'):
            self.invoke(request)

    def test_audit_visual_context_retains_leaf_spec_without_mutating_state(self):
        analysis = self.ref(self.f.run / 'staging/dimensions.json', '{"dimensions": []}')
        self.module['plan']['dimension_analysis_ref'] = analysis
        self.module['results']['PV'] = {'quality': 'yellow-blocked'}
        self.state['global_paths'] = []
        self.state['audit_assignment'] = {'assignment_id': 'A1', 'role': 'auditor', 'instance_id': 'auditor',
            'closed': False, 'scope_policy': 'non-green-only', 'path_ids': ['PV'],
            'snapshot': {'M001': self.module['code_baseline']}}
        self.state['audit_test_assignment'] = {**self.state['audit_assignment'], 'assignment_id': 'A1-TEST',
            'role': 'test-runner', 'instance_id': 'independent-runner', 'audit_assignment_id': 'A1'}
        self.actor = {'role': 'test-runner', 'instance_id': 'independent-runner'}
        request = self.request('visual-capture')
        request.update(module_id='GLOBAL', assignment_id='A1-TEST', fencing_token=None)
        before = copy.deepcopy(self.state)
        module, _ = lean_worker.assignment(self.state, request, self.actor)
        self.assertEqual(module['path_dimension_analysis_refs'], {'PV': analysis})
        self.assertEqual(self.state, before)


if __name__ == '__main__':
    unittest.main()
