"""Prepared tests, delivered context and fidelity evidence retain the existing Run and gates."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import api_contract
import design_stage
import dimensions
import experience
import ledger
import migration_report
import status_view
import test_design_stage
import test_dimensions
import test_ledger
import test_progressive_fidelity
from contracts import Rejected, check_ref, read_json
from execute_test import execute


class PreparedTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.global_plan()

    def design(self):
        f = self.f; plan = f.plan()
        a, result = test_design_stage.start_design(f, plan)
        script = f.ref('prepared.py', '''import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()
q=json.load(open(a.query_file));assert q['frozen_test_assets'][0]['asset_id']=='TEST1'
actual=int(Path('m1/code.py').read_text().split('=')[1])
json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':actual,'passed':actual==2}]},open(a.result_file,'w'))
''')
        result['test_assets'] = [{'asset_id': 'TEST1', 'kind': 'script', 'ref': script, 'path_ids': ['P1'],
                                 'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}]}]
        return plan, a, result

    def freeze(self, plan, a, result):
        f = self.f; test_design_stage.submit_design(f, a, result)
        f.call('accept', {'assignment_id': a['assignment_id'], 'review_ref': f.ref('review.md', 'Independent coverage reviewed')})
        plan['definitions'] = [r for r in plan['definitions'] if r['kind'] != 'test-design']
        f.call('plan', {'plan_ref': f.ref('asset-plan.json', plan)}, role='spec-designer')
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D-ASSET'); f.call('freeze', {'decision_id': 'D-ASSET'})

    def test_prepared_script_freezes_and_executes_only_after_accepted_code(self):
        f = self.f; plan, a, result = self.design()
        with self.assertRaisesRegex(Rejected, 'test assignment required'):
            execute(f.root, 'M001', a['assignment_id'], 'P1', [sys.executable, result['test_assets'][0]['ref']['path']], f.target, f.base/'early')
        self.assertFalse((f.base/'early').exists())
        self.freeze(plan, a, result)
        definition = {**result['test_assets'][0]['ref'], 'kind': 'test-script'}
        self.assertIn(definition, f.state()['modules']['M001']['plan']['definitions'])
        f.implementation(); a = f.assign('test-runner', 'EXEC')
        receipt_ref = execute(f.root, 'M001', 'EXEC', 'P1', [sys.executable, definition['path']], f.target, f.base/'executed')
        receipt = read_json(check_ref(receipt_ref))
        query = read_json(check_ref(receipt['query_ref']))
        self.assertEqual(query['frozen_test_assets'], result['test_assets'])
        assertions = read_json(check_ref(receipt['result_ref']))['assertions']
        f.submit({'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'M001',
            'assignment_id': 'EXEC', 'actor_instance_id': 'test-runner', 'freeze_id': a['freeze_id'], 'code_baseline': a['code_baseline'],
            'paths': [{'path_id': 'P1', 'test_run_id': receipt['test_run_id'], 'quality': 'green-passed', 'executed': True,
                'execution_receipt': receipt_ref, 'assertions': assertions, 'retest_of': None}]}, a)
        f.call('accept', {'assignment_id': 'EXEC'})
        self.assertEqual(f.state()['modules']['M001']['results']['P1']['quality'], 'green-passed')

    def test_asset_drift_invalidates_frozen_inputs(self):
        plan, a, result = self.design(); self.freeze(plan, a, result)
        Path(result['test_assets'][0]['ref']['path']).write_text('changed acceptance')
        self.assertFalse(design_stage.ready(self.f.state(), self.f.state()['modules']['M001']))
        with self.assertRaises(Rejected): self.f.assign('implementer', 'BAD')

    def test_asset_cannot_claim_execution_or_map_unowned_assertion(self):
        plan, a, result = self.design()
        for field, value in (('executed', True), ('assertions', [{'path_id': 'P1', 'assertion_id': 'UNKNOWN'}])):
            bad = copy.deepcopy(result); bad['test_assets'][0][field] = value
            with self.assertRaises(Rejected): test_design_stage.submit_design(self.f, a, bad)
        bad = copy.deepcopy(result)
        outside = self.f.target/'source.py'; outside.write_text('target source')
        from contracts import file_ref
        bad['test_assets'][0]['ref'] = file_ref(outside)
        with self.assertRaisesRegex(Rejected, 'staging'): test_design_stage.submit_design(self.f, a, bad)


class ContextAccounting(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups); self.f.prepare()

    def report(self, rows):
        f = self.f; s = f.state(); step = s['next_steps'][0]
        return f.call('session', request={'schema_version': 1, 'request_id': 'input-'+str(f.n), 'run_id': 'demo',
            'module_id': 'M001', 'expected_revision': s['modules']['M001']['revision'], 'operation': 'session',
            'payload': {'role': 'implementer', 'session_id': 'S1'},
            'hint': {'session_id': 'S1', 'card_sha256': step['card_sha256'], 'context_inputs': rows}})

    def test_real_log_bytes_trigger_rotation_and_repeated_content_is_not_recounted(self):
        f = self.f; f.call('session', {'role': 'implementer', 'session_id': 'S1'})
        phase = f.state()['modules']['M001']['phase']; ref = f.ref('large.log', 'x'*100001)
        self.report([{'kind': 'log', 'ref': ref}]); s = f.state()
        self.assertEqual(s['next_steps'][0]['session_rotate']['reason'], 'context-load')
        self.assertEqual(ledger.context_load(s, 'S1')['input_bytes'], 100001)
        self.report([{'kind': 'log', 'ref': ref}, {'kind': 'tool', 'ref': f.ref('same.log', 'x'*100001)}])
        s = f.state(); self.assertEqual(ledger.context_load(s, 'S1')['input_count'], 1)
        self.assertEqual((s['run_id'], s['modules']['M001']['phase']), ('demo', phase))
        self.assertEqual(ledger.context_load(s, 'NEW')['reported_bytes'], 0)

    def test_drifted_delivery_is_rejected_without_partial_accounting(self):
        f = self.f; ref = f.ref('log.txt', 'original'); Path(ref['path']).write_text('changed')
        before = f.state()['last_sequence']
        with self.assertRaises(Rejected): self.report([{'kind': 'log', 'ref': ref}])
        self.assertEqual(f.state()['last_sequence'], before)
        self.assertEqual(ledger.context_load(f.state(), 'S1')['input_count'], 0)

    def test_global_host_delivery_is_accounted_on_the_same_run(self):
        f = self.f; s = f.state(); ref = f.ref('global-log.txt', 'g'*100001)
        payload = {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(f.target/'m2')], 'dependencies': []}
        f.call('register', payload, role='global-orchestrator', module=None, request={
            'schema_version': 1, 'request_id': 'global-input', 'run_id': 'demo', 'module_id': None,
            'expected_revision': s['revision'], 'operation': 'register', 'payload': payload,
            'hint': {'session_id': 'GLOBAL-S', 'card_sha256': s['global_next_step'].get('card_sha256', ''),
                'context_inputs': [{'kind': 'log', 'ref': ref}]}})
        s = f.state(); self.assertEqual(s['run_id'], 'demo')
        self.assertEqual(s['global_next_step']['session_rotate']['reason'], 'context-load')
        self.assertEqual(s['global_next_step']['context_load']['input_bytes'], 100001)

    def test_step_history_is_bounded_and_complete_history_stays_in_state(self):
        s = self.f.state(); s['modules']['M001']['planning_history'] = [{'reason': str(i)} for i in range(20)]
        s['next_steps'][0]['operation'] = 'plan'
        view = status_view.select(s, 'step', 'M001')
        self.assertEqual(view['planning_history_count'], 20)
        self.assertEqual([r['reason'] for r in view['planning_history']], ['15', '16', '17', '18', '19'])
        self.assertEqual(len(s['modules']['M001']['planning_history']), 20)


class FidelityConditions(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.condition = {'condition_id': 'FONT', 'condition': 'font scale changes layout', 'status': 'applicable',
            'reason': 'source uses scalable text', 'evidence_refs': [self.f.ref('source.md', 'sp + visibility')],
            'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}]}

    def test_condition_rejects_static_only_and_other_item_assertions(self):
        item = {'fidelity_conditions': [self.condition]}; paths = {'P1': {'kind': 'visual', 'expected_assertions': [{'assertion_id': 'A1'}]}}
        trace = {'assertions': [{'path_id': 'P1', 'assertion_id': 'A1', 'extra': 'mapped'}]}
        dimensions.fidelity_conditions(item, paths, trace)
        paths['P1']['kind'] = 'static'
        with self.assertRaisesRegex(Rejected, 'behavioral'): dimensions.fidelity_conditions(item, paths, trace)
        paths['P1']['kind'] = 'visual'
        with self.assertRaisesRegex(Rejected, 'item-owned'): dimensions.fidelity_conditions(item, paths, {'assertions': []})

    def test_condition_report_needs_current_execution_and_exact_assertion(self):
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'not-applicable'}, {'dimension': 'Logic', 'items': [
            {'item_id': 'TEXT', 'fidelity_conditions': [self.condition]}]}]}
        ref = self.f.ref('conditions.json', analysis); state = {'modules': {'M001': {'plan': {'dimension_analysis_ref': ref}}}}
        row = {'module_id': 'M001', 'path_id': 'P1', 'kind': 'visual', 'quality': 'green-passed',
            'executed': True, 'attempt_executed': True, 'stale': False, 'assertions': [{'assertion_id': 'A1', 'passed': True}]}
        def status(rows): return migration_report.fidelity(state, rows, check_ref)[2]['conditions'][0]['status']
        self.assertEqual(status([row]), 'verified')
        for key, value in (('stale', True), ('attempt_executed', False), ('assertions', [{'assertion_id': 'OTHER', 'passed': True}])):
            self.assertEqual(status([{**row, key: value}]), 'not-verified')
        self.assertEqual(status([]), 'not-verified')

    def test_child_cannot_drop_parent_condition(self):
        t = test_dimensions.DimensionTests(); t.setUp(); self.addCleanup(t.doCleanups)
        t.root(); s = t.f.state(); parent = s['modules']['M010']; doc = read_json(check_ref(parent['dimension_analysis_ref']))
        condition = {**self.condition, 'assertions': []}
        doc['dimensions'][1]['items'][0]['fidelity_conditions'] = [condition]
        parent['dimension_analysis_ref'] = t.f.ref('reviewed-root.json', doc); t.root_ref = parent['dimension_analysis_ref']
        proposal = t.proposal()
        with self.assertRaisesRegex(Rejected, 'omit parent fidelity'): dimensions.partition(s, parent, proposal)
        child = proposal['children'][0]; child_doc = read_json(check_ref(child['dimension_analysis_ref']))
        child_doc['dimensions'][1]['items'][0]['fidelity_conditions'] = [condition]
        child['dimension_analysis_ref'] = t.f.ref('reviewed-child.json', child_doc)
        dimensions.partition(s, parent, proposal)


class RetrievalAndDiscovery(unittest.TestCase):
    def test_long_scope_matches_cause_and_dimension_without_loading_lesson_body(self):
        entries = [{'kind': kind, 'summary': kind, 'applicability': 'Search image filters', 'root_cause': 'loader-error',
            'lesson_ref': {'path': '/unopened/'+kind}} for kind in ('fix-pattern', 'failed-strategy')]
        m = {'scope': {'in': ['Implement search results with filters and error handling']}, 'results': {'P': {'root_cause': {'category': 'loader-error'}}}}
        found = experience.candidates({'runs': {'old': {'entries': entries}}}, m)
        self.assertEqual(found[0]['kind'], 'failed-strategy'); self.assertEqual(len(found), 2)
        self.assertEqual(experience.candidates({'runs': {'old': {'entries': entries}}}, {'scope': {'in': ['Orders']}}), [])

    def test_api_discovery_scope_must_cover_recorded_source(self):
        t = test_progressive_fidelity.ApiContractTests(); t.setUp(); self.addCleanup(t.doCleanups)
        analysis = t.analysis(); analysis['api_review'] = {'status': 'applicable', 'reason': 'Scoped API source reviewed',
            'evidence_refs': [t.source['source_ref']], 'discovery_refs': [t.f.ref('other-source.md', 'unrelated source')]}
        with self.assertRaisesRegex(Rejected, 'discovery scope'): api_contract.load(analysis, t.items)
        analysis['api_review']['discovery_refs'] = [t.source['source_ref']]
        self.assertIn('QUERY', api_contract.load(analysis, t.items)[1])


if __name__ == '__main__': unittest.main()
