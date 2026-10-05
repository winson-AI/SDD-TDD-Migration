"""Cross-stage test inputs, conditional coverage and actual host handoff receipts."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import context_handoff
import context_readiness
import dimensions
import ledger
import prepared_tests
import test_design_stage
import test_dimensions
import test_ledger
import test_planning_evidence
import test_split_testing
from contracts import Rejected, check_ref, file_ref, read_json, validate_result
from execute_test import execute


class AssetHandoffTests(unittest.TestCase):
    def test_native_global_assets_require_own_design_and_independent_auditor(self):
        import workflow
        import audit_code_review
        t = test_planning_evidence.PreparedTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f = t.f; plan, assignment, design = t.design()
        design['paths'][0]['path_id'] = 'GP1'
        design['test_assets'][0]['path_ids'] = ['GP1']
        design['test_assets'][0]['assertions'][0]['path_id'] = 'GP1'
        path = {**design['paths'][0], 'test_design_ref': f.ref('global-design.json', design)}
        with self.assertRaisesRegex(Rejected, 'another module'): workflow.global_paths_check([path], ['C1'])
        design['module_id'] = 'GLOBAL'; design['actor_instance_id'] = 'auditor'
        path['test_design_ref'] = f.ref('global-design.json', design)
        workflow.global_paths_check([path], ['C1'])
        # Independent, settled fixture isolates author identity from unrelated execution gates.
        g = test_ledger.FlowTests(); g.setUp(); self.addCleanup(g.doCleanups); g.finish_module()
        s = g.state(); s['global_paths'] = [path]
        with self.assertRaisesRegex(Rejected, 'GLOBAL script author'):
            audit_code_review.accept(s, {}, {'role': 'auditor', 'instance_id': 'auditor'})

    def test_deferred_module_retest_keeps_prepared_inputs_in_global_scope(self):
        t = test_split_testing.SplitTestingTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f = t.f; f.global_plan(); plan = f.plan()
        a, design = test_design_stage.start_design(f, plan)
        script = f.ref('prepared.py', '''import argparse,json
p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()
q=json.load(open(a.query_file))
if q['path_id']=='P1':
 assert q['frozen_test_assets'][0]['asset_id']=='SCRIPT'
 assert q['test_asset_binding']['module_id']=='M001'
json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':2,'passed':True}]},open(a.result_file,'w'))
''')
        design['test_assets'] = [{'asset_id': 'SCRIPT', 'kind': 'script', 'ref': script, 'path_ids': ['P1'],
            'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}]}]
        test_design_stage.submit_design(f, a, design)
        f.call('accept', {'assignment_id': a['assignment_id'], 'review_ref': f.ref('review.md', 'Reviewed independent test script')})
        plan['definitions'] = [r for r in plan['definitions'] if r['kind'] != 'test-design']
        f.call('plan', {'plan_ref': f.ref('prepared-plan.json', plan)}, role='spec-designer')
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D-PREP'); f.call('freeze', {'decision_id': 'D-PREP'})
        f.implementation(); t.compile(); t.defer()
        old = f.state(); owner = old['modules']['M001']; f.test_argv = [sys.executable, script['path']]
        refs = context_readiness.input_refs(old, None, 'audit-execution')
        self.assertIn(script, refs)
        test_ledger.code_review(f)
        f.call('audit-assign', {'assignment_id': 'AUD', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        s = f.state(); scope = ledger.audit_scope(s); records = []
        for path in scope['plan']['paths']:
            ref = execute(f.root, 'GLOBAL', 'AUD', path['path_id'], f.test_argv, f.target, f.base/('audit-'+path['path_id']))
            receipt = read_json(check_ref(ref))
            if path['path_id'] == 'P1':
                self.assertEqual(receipt['test_asset_binding']['freeze_id'], owner['freeze_id'])
                self.assertEqual(receipt['test_asset_usage']['entrypoint_ids'], ['SCRIPT'])
                bad = {**receipt, 'test_asset_binding': {**receipt['test_asset_binding'], 'freeze_id': 'wrong'}}
                with self.assertRaisesRegex(Rejected, 'binding mismatch'):
                    prepared_tests.validate_receipt(scope, path, bad, 'green-passed')
            records.append({'path_id': path['path_id'], 'test_run_id': receipt['test_run_id'], 'executed': True,
                'quality': 'green-passed', 'execution_receipt': ref,
                'assertions': read_json(check_ref(receipt['result_ref']))['assertions'],
                'retest_of': scope['results'].get(path['path_id'], {}).get('test_run_id')})
        report = {'schema_version': 1, 'kind': 'tests', 'run_id': s['run_id'], 'module_id': 'GLOBAL',
            'assignment_id': 'AUD', 'actor_instance_id': 'auditor', 'freeze_id': scope['freeze_id'],
            'code_baseline': scope['code_baseline'], 'snapshot': s['audit_assignment']['snapshot'], 'paths': records}
        f.call('audit', {'report_ref': f.ref('audit.json', report)}, role='auditor', module=None)
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')
        f.call('complete', {'dod_ref': f.ref('post-audit-dod.md', 'Build and restored automation independently passed')})
        self.assertEqual(f.state()['quality'], 'green-passed')
        self.assertEqual(f.state()['run_id'], old['run_id'])

    def test_unit_command_receives_assets_and_unused_fixture_cannot_claim_green(self):
        t = test_planning_evidence.PreparedTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f = t.f; plan, a, design = t.design()
        fixture = f.ref('unit-fixture.json', {'expected': 2})
        code = '''import json,os
q=json.load(open(os.environ['SDD_TEST_QUERY_FILE']))
a=q['frozen_test_assets'][0]
assert json.load(open(a['ref']['path']))['expected']==2
json.dump([{'asset_id':a['asset_id'],'ref':a['ref']}],open(os.environ['SDD_TEST_ASSET_USAGE_FILE'],'w'))
'''
        unit = {'path_id': 'P1', 'kind': 'unit', 'name': 'unit behavior', 'case_id': 'C1', 'requirement_id': 'R1',
            'command': {'argv': [sys.executable, '-c', code], 'cwd': str(f.target), 'timeout_seconds': 20,
                        'selection_ref': f.ref('unit-selection.md', 'Approved unit fixture command')},
            'expected_assertions': [{'assertion_id': 'A1', 'expected': 0}]}
        plan['paths'] = design['paths'] = [unit]
        design['test_assets'] = [{'asset_id': 'FIXTURE', 'kind': 'fixture', 'ref': fixture, 'path_ids': ['P1']}]
        t.freeze(plan, a, design); f.implementation(); assignment = f.assign('test-runner', 'UNIT')
        ref = execute(f.root, 'M001', 'UNIT', 'P1', unit['command']['argv'], f.target, f.base/'unit')
        receipt = read_json(check_ref(ref)); module = f.state()['modules']['M001']
        prepared_tests.validate_receipt(module, unit, receipt, 'green-passed')
        self.assertEqual(receipt['test_asset_usage']['reported_ids'], ['FIXTURE'])
        usage = Path(receipt['test_asset_usage_ref']['path']); usage.unlink()
        missing = {**receipt, 'test_asset_usage_ref': None, 'test_asset_usage': {'entrypoint_ids': [], 'reported_ids': []}}
        with self.assertRaisesRegex(Rejected, 'consumption'):
            prepared_tests.validate_receipt(module, unit, missing, 'green-passed')
        prepared_tests.validate_receipt(module, unit, missing, 'yellow-blocked')
        usage.write_text('{malformed')
        invalid = {**receipt, 'test_asset_usage_ref': file_ref(usage),
                   'test_asset_usage': prepared_tests.usage(receipt['test_asset_binding'], receipt['requested_argv'], usage)}
        with self.assertRaisesRegex(Rejected, 'valid test asset usage'):
            prepared_tests.validate_receipt(module, unit, invalid, 'green-passed')
        prepared_tests.validate_receipt(module, unit, invalid, 'yellow-blocked')


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_preparation_cannot_be_omitted_or_deferred_at_freeze(self):
        f = self.f; f.global_plan(); a, design = test_design_stage.start_design(f, f.plan())
        with self.assertRaisesRegex(Rejected, 'preparation review'):
            prepared_tests.preparation(design, required=True)
        review = {'status': 'deferred', 'reason': 'Fixture absent', 'asset_ids': [], 'evidence_refs': [design['design_ref']],
                  'owner': 'MO', 'next_action': 'Prepare approved fixture'}
        design['paths'][0]['preparation'] = review
        prepared_tests.preparation(design, required=True)
        with self.assertRaisesRegex(Rejected, 'before freeze'):
            prepared_tests.preparation(design, required=True, freezing=True)
        review['status'] = 'existing'
        prepared_tests.preparation(design, required=True, freezing=True)

    def test_technical_preparation_does_not_redefine_business_acceptance(self):
        import control_policy
        paths = self.f.plan()['paths']; updated = copy.deepcopy(paths)
        updated[0]['preparation'] = {'status': 'prepared', 'asset_ids': ['APPROVED-SCRIPT']}
        self.assertEqual(control_policy.acceptance(paths), control_policy.acceptance(updated))
        updated[0]['expected_assertions'][0]['expected'] = 'weakened result'
        self.assertNotEqual(control_policy.acceptance(paths), control_policy.acceptance(updated))

    def test_condition_review_requires_source_exclusions_and_owned_conditions(self):
        proof = self.f.ref('source.xml', '<TextView textSize="16sp"/>')
        row = {'dimension': 'UI', 'status': 'applicable', 'items': [{'item_id': 'TEXT', 'fidelity_conditions': [
            {'condition_id': 'SCALE', 'status': 'applicable'}]}]}
        doc = {'dimensions': [row]}
        with self.assertRaisesRegex(Rejected, 'condition review required'): dimensions.coverage_review(doc, True)
        row['condition_review'] = {facet: {'reason': 'Reviewed source; no conditional variant', 'evidence_refs': [proof],
            'condition_refs': []} for facet in dimensions.CONDITION_FACETS['UI']}
        with self.assertRaisesRegex(Rejected, 'omits applicable'): dimensions.coverage_review(doc, True)
        row['condition_review']['font-scale']['condition_refs'] = [{'item_id': 'TEXT', 'condition_id': 'SCALE'}]
        dimensions.coverage_review(doc, True)
        row['condition_review']['theme']['evidence_refs'] = []
        with self.assertRaisesRegex(Rejected, 'source evidence'): dimensions.coverage_review(doc, True)
        dimensions.coverage_review({'dimensions': [{'dimension': 'Logic', 'status': 'applicable'}]}, True)

    def test_api_applicability_requires_discovery_on_new_runs_only(self):
        t = test_dimensions.DimensionTests(); t.setUp(); self.addCleanup(t.doCleanups); t.root()
        s = t.f.state(); module = s['modules']['M010']; doc = read_json(check_ref(module['dimension_analysis_ref']))
        doc['api_review'].pop('discovery_refs'); module['dimension_analysis_ref'] = t.f.ref('old-discovery.json', doc)
        dimensions.allocation(s, module)
        s['planning_coverage_required'] = True
        with self.assertRaisesRegex(Rejected, 'API discovery scope'): dimensions.allocation(s, module)


class HostHandoffTests(unittest.TestCase):
    def setUp(self):
        f = self.f = test_ledger.FlowTests(); call = f.call
        def gated(op, payload=None, **kwargs):
            if op == 'init': payload = {**payload, 'host_handoff_required': True}
            return call(op, payload, **kwargs)
        f.call = gated; f.setUp(); self.addCleanup(f.doCleanups); f.prepare()

    def payload(self, mid):
        f = self.f; s = f.state(); role = 'implementer' if mid else 'global-orchestrator'
        checkpoint = context_handoff.checkpoint(s, s['modules'][mid] if mid else None, role, 'old')
        ref = f.ref(('module' if mid else 'global')+'-checkpoint.json', checkpoint)
        payload = {'role': role, 'session_id': 'new', 'reason': 'context-rotation', 'checkpoint_ref': ref}
        receipt = {'producer': 'host', 'status': 'restored', 'run_id': 'demo', 'module_id': mid, 'role': role,
            'previous_session_id': 'old', 'session_id': 'new', 'checkpoint_ref': ref, 'restored_refs': checkpoint['resume_refs'],
            'evidence_refs': [f.ref('host-transport.json', {'new_session_id': 'new', 'restored': True})]}
        return payload, receipt

    def test_module_rotation_requires_host_restore_and_keeps_business_state(self):
        f = self.f; f.call('session', {'role': 'implementer', 'session_id': 'old'})
        before = f.state()['modules']['M001']; payload, receipt = self.payload('M001')
        with self.assertRaises(Rejected): f.call('session', payload)
        payload['host_receipt_ref'] = f.ref('host-restore.json', {**receipt, 'restored_refs': []})
        with self.assertRaisesRegex(Rejected, 'restored inputs'): f.call('session', payload)
        payload['host_receipt_ref'] = f.ref('host-restore.json', receipt); f.call('session', payload)
        s = f.state(); after = s['modules']['M001']
        self.assertEqual(s['run_id'], 'demo'); self.assertEqual(after['sessions']['implementer']['session_id'], 'new')
        self.assertEqual({k: before[k] for k in ('plan_ref', 'freeze_id', 'results', 'phase')},
                         {k: after[k] for k in ('plan_ref', 'freeze_id', 'results', 'phase')})
        self.assertEqual(ledger.context_load(s, 'new')['reported_bytes'], 0)

    def test_global_rotation_cannot_be_faked_by_a_new_hint(self):
        f = self.f; f.call('session', {'role': 'global-orchestrator', 'session_id': 'old'}, role='host', module=None)
        s = f.state()
        req = {'schema_version': 1, 'request_id': 'unacknowledged', 'run_id': 'demo', 'module_id': None,
            'expected_revision': s['revision'], 'operation': 'global-plan', 'payload': {},
            'hint': {'session_id': 'new', 'card_sha256': ''}}
        with self.assertRaisesRegex(Rejected, 'host session handoff'): f.call('global-plan', request=req, role='global-orchestrator', module=None)
        payload, receipt = self.payload(None)
        payload['host_receipt_ref'] = f.ref('global-restore.json', receipt)
        f.call('session', payload, role='host', module=None)
        self.assertEqual(f.state()['context_sessions']['global-orchestrator'], 'new')
        self.assertEqual(f.state()['session_history'][-1]['session_id'], 'old')
        self.assertEqual(f.state()['run_id'], 'demo')

    def test_stale_restore_cannot_erase_new_module_state_or_reuse_old_session(self):
        f = self.f; f.call('session', {'role': 'implementer', 'session_id': 'old'})
        payload, receipt = self.payload('M001'); payload['host_receipt_ref'] = f.ref('restore.json', receipt)
        f.call('session', {'role': 'implementer', 'session_id': 'old'})
        with self.assertRaisesRegex(Rejected, 'checkpoint stale'): f.call('session', payload)
        with self.assertRaisesRegex(Rejected, 'distinct new session'):
            f.call('session', {**payload, 'session_id': 'old'})

    def test_delivery_total_counts_repeated_inputs_without_inflating_distinct_material(self):
        s = {}; ref = self.f.ref('log.txt', 'abcd'); hint = {'session_id': 'S', 'context_inputs': [{'kind': 'log', 'ref': ref}]}
        ledger.record_inputs(s, hint); ledger.record_inputs(s, hint); s['modules'] = {}
        load = ledger.context_load(s, 'S')
        self.assertEqual((load['input_bytes'], load['input_delivered_bytes'], load['input_delivery_count']), (4, 8, 2))

    def test_global_candidates_use_current_goal_without_opening_lesson_bodies(self):
        f = self.f; s = f.state(); s['global_spec'] = f.ref('new-goal.md', 'Search image filters')
        lesson = {'kind': 'slicing-gap', 'summary': 'Search image filters share a provider', 'applicability': 'Search image filters',
                  'lesson_ref': {'path': '/not-opened/lesson.json', 'sha256': '0'*64}}
        index = f.ref('experience-index.json', {'runs': {'prior-run': {'entries': [lesson]}}})
        s['project_context_ref'] = {'path': '/snapshot', 'sha256': 'stub'}
        with patch('project_context.verify_snapshot', return_value={'source_refs': {'experience_ref': index}}):
            step = ledger.with_card(s, None, {'role': 'global-orchestrator', 'operation': 'register'})
        self.assertEqual(step['lesson_candidates'][0]['lesson_ref'], lesson['lesson_ref'])


if __name__ == '__main__': unittest.main()
