"""Scoped telemetry coverage and N/A progress, using the existing Ledger gates."""
import copy
from pathlib import Path
import unittest

import test_ledger
from contracts import Rejected, digest, validate_plan


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def plan(self, applicable=False):
        f = self.f; plan = f.plan()
        proof = f.ref('telemetry-scope.md', 'Inspected business entry and provider; frozen event contract or no telemetry in scope.')
        plan['telemetry'] = {'status': 'not-applicable', 'reason': 'No telemetry responsibility in this scope',
            'evidence_refs': [proof], 'events': [],
            'tasks': [{'task_id': 'T1', 'status': 'not-applicable', 'reason': 'plain business logic', 'event_ids': []}]}
        if applicable:
            plan['telemetry'].update(status='applicable', reason='business entry emits an event', events=[{
                'event_id': 'EV1', 'legacy_event': 'legacy_success', 'target_event': 'success',
                'trigger': 'one event after successful operation', 'non_triggers': 'failed operation',
                'payload_contract': 'value integer 2', 'delivery_semantics': 'existing synchronous dispatch; no queue',
                'production_binding': 'existing target provider', 'verification_level': 'sdk-dispatched',
                'task_ids': ['T1'], 'tests': [{'path_id': 'P1', 'assertion_ids': ['A1']}], 'evidence_refs': [proof]}])
            plan['telemetry']['tasks'][0].update(status='applicable', reason='emits event', event_ids=['EV1'])
        return plan

    def freeze(self, plan):
        f = self.f; f.global_plan()
        f.call('plan', {'plan_ref': f.ref('p.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})

    def test_absent_legacy_contract_does_not_add_a_gate(self):
        f = self.f; self.freeze(f.plan()); f.implementation()
        self.assertEqual(f.state()['modules']['M001']['phase'], 'testing')

    def test_not_applicable_completes_without_extra_paths_or_fixer(self):
        f = self.f; plan = self.plan(); before = copy.deepcopy(plan['paths'])
        self.freeze(plan); f.implementation()
        assignment, report = f.make_test_result()
        f.submit(report, assignment); f.call('accept', {'assignment_id': 'TEST1'})
        f.call('complete', {'dod_ref': f.ref('dod.md', 'all business paths passed; telemetry N/A'), 'checks_passed': True})
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'completed'); self.assertEqual(m['quality'], 'green-passed')
        self.assertEqual(m['plan']['paths'], before); self.assertEqual(m['total_fix_rounds'], 0)

    def test_applicable_module_can_have_not_applicable_task(self):
        f = self.f; plan = self.plan(True)
        plan['tasks'].append({'task_id': 'T2', 'requirement_ids': ['R1'], 'path_ids': ['P1']})
        for d in plan['definitions']:
            if d['kind'] == 'tasks':
                d.update(f.ref('tasks-mixed.md', '- [ ] T1 event\n- [ ] T2 plain formatting\n'))
        plan['telemetry']['tasks'].append({'task_id': 'T2', 'status': 'not-applicable', 'reason': 'formatting only', 'event_ids': []})
        self.freeze(plan)
        self.assertTrue(f.state()['modules']['M001']['freeze_id'])

    def test_event_mapping_cannot_use_build_unknown_assertions_or_n_a(self):
        f = self.f; original = self.plan(True); module = f.state()['modules']['M001']
        for change in ('build', 'assertion', 'task', 'na', 'unknown-status', 'empty-events', 'missing-contract'):
            plan = copy.deepcopy(original); event = plan['telemetry']['events'][0]
            if change == 'build': plan['paths'][0]['kind'] = 'build'
            if change == 'assertion': event['tests'][0]['assertion_ids'] = ['MISSING']
            if change == 'task': event['task_ids'] = ['UNKNOWN']
            if change == 'na': plan['telemetry']['status'] = 'not-applicable'
            if change == 'unknown-status': plan['telemetry']['status'] = 'unresolved'
            if change == 'empty-events': plan['telemetry']['events'] = []
            if change == 'missing-contract': event.pop('payload_contract')
            with self.subTest(change=change), self.assertRaises(Rejected): validate_plan(plan, module)

    def test_stale_telemetry_evidence_only_blocks_its_owner(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [],
                           'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        plan = self.plan(True); self.freeze(plan)
        peer = f.plan(); peer['module_id'] = 'M002'; peer['paths'][0]['path_id'] = 'P2'; peer['tasks'][0]['path_ids'] = ['P2']
        f.call('plan', {'plan_ref': f.ref('peer.json', peer)}, role='spec-designer', module='M002')
        f.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002',
                           'subject_sha256': digest(peer), 'human_source_ref': f.ref('approval2.md', 'approved')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'D2'}, module='M002')
        Path(plan['telemetry']['evidence_refs'][0]['path']).write_text('changed source review')
        with self.assertRaises(Rejected):
            f.call('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'impl1'})
        f.call('assign', {'assignment_id': 'I2', 'role': 'implementer', 'instance_id': 'impl2'}, module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'], 'implementing')
