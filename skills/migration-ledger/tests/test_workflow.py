import copy
import json
from pathlib import Path
import shutil
import sys
import unittest
import unittest.mock

import test_ledger
from contracts import Rejected, digest, file_ref
import ledger
import reading
import workflow
from execute_test import execute


class WorkflowTests(unittest.TestCase):
    # Reuse fixtures, not the inherited old test suite.
    setUp = test_ledger.FlowTests.setUp
    ref = test_ledger.FlowTests.ref
    state = test_ledger.FlowTests.state
    call = test_ledger.FlowTests.call
    plan = test_ledger.FlowTests.plan
    global_plan = test_ledger.FlowTests.global_plan
    prepare = test_ledger.FlowTests.prepare
    approve = test_ledger.FlowTests.approve
    assign = test_ledger.FlowTests.assign
    submit = test_ledger.FlowTests.submit
    implementation = test_ledger.FlowTests.implementation
    make_test_result = test_ledger.FlowTests.make_test_result

    def new_entry_run(self, config):
        original = self.state()
        self.root = self.base / f'entry-run-{self.n}'
        return self.call('init', {**{key: original[key] for key in
            ('dimension_slicing_required', 'split_testing_required', 'context_readiness_required', 'target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec', 'new_architecture', 'global_paths')},
            **config}, role='host')

    def register_entry_module(self, mid='M001', cases=None, dependencies=None):
        return self.call('register', {'module_id': mid, 'case_ids': ['C1'] if cases is None else cases,
            'dependencies': [] if dependencies is None else dependencies,
            'write_paths': [str(self.target / ('m1' if mid == 'M001' else 'm2'))]},
            role='global-orchestrator', module=None)

    def test_project_entry_remains_default_and_allows_multiple_modules(self):
        self.assertEqual(self.state()['entry_mode'], 'project')
        self.register_entry_module('M002')
        self.assertEqual(set(self.state()['modules']), {'M001', 'M002'})

    def test_single_module_entry_requires_valid_mode_and_selected_id(self):
        original_root = self.root
        for config in ({'entry_mode': 'unknown'}, {'entry_mode': 'single-module'},
                       {'entry_mode': 'single-module', 'single_module_id': 'login'},
                       {'entry_mode': 'project', 'single_module_id': 'M001'}):
            with self.subTest(config=config):
                self.root = original_root
                with self.assertRaises(Rejected):
                    self.new_entry_run(config)

    def test_single_module_rejects_expansion_dependencies_and_missing_cases(self):
        self.new_entry_run({'entry_mode': 'single-module', 'single_module_id': 'M001'})
        with self.assertRaisesRegex(Rejected, 'only permits the selected module'):
            self.register_entry_module('M002')
        with self.assertRaisesRegex(Rejected, 'must be independent'):
            self.register_entry_module(dependencies=['M002'])
        with self.assertRaisesRegex(Rejected, 'case coverage mismatch'):
            self.register_entry_module(cases=[])
        self.register_entry_module()
        with self.assertRaisesRegex(Rejected, 'only permits the selected module'):
            self.register_entry_module('M002')

    def test_single_module_green_flow_still_requires_independent_auditor(self):
        self.new_entry_run({'entry_mode': 'single-module', 'single_module_id': 'M001'})
        self.register_entry_module()
        # Real Ledger transitions and subprocess receipts: module completion alone
        # remains Yellow at run scope; independent Auditor evidence makes it Green.
        test_ledger.FlowTests.test_green_flow_and_independent_global_audit(self)
        self.assertEqual(self.state()['entry_mode'], 'single-module')
        self.assertEqual(set(self.state()['modules']), {'M001'})

    def test_single_module_leftovers_still_enter_auditor_collection(self):
        self.new_entry_run({'entry_mode': 'single-module', 'single_module_id': 'M001'})
        self.register_entry_module()
        self.failed_module('environment'); self.defer('environment')
        test_ledger.code_review(self)
        self.call('audit-collect', {'batch_id': 'SINGLE-AUDIT', 'auditor_instance_id': 'auditor'},
                  role='global-orchestrator', module=None)
        batch = self.state()['audit_batch']
        self.assertEqual(batch['status'], 'collected')
        self.assertEqual(set(batch['sources']), {'M001'})
        self.assertTrue(batch['findings'])

    def boundary_plan(self):
        s = self.state()
        return {'global_spec': s['global_spec'], 'new_architecture': s['new_architecture'],
                'requirement_owners': {'R1': ['M001']}, 'case_owners': {'C1': ['M001', 'GLOBAL']},
                'boundary_review': {'issues': [{'question_id': 'B1', 'kind': 'uncertain',
                    'module_ids': ['M001'], 'question': 'Does this scope include guest access?',
                    'proposed_resolution': 'Guest access is excluded from M001.'}]}}

    def accept_boundary_plan(self, plan, decision_id=None):
        payload = {'plan_ref': self.ref(f'boundary-plan-{self.n}.json', plan),
                   'review_ref': self.ref('boundary-review.md', 'scope and coverage reviewed')}
        if decision_id:
            payload['boundary_decision_id'] = decision_id
        return self.call('global-plan', payload, role='global-orchestrator', module=None)

    def approve_boundaries(self, plan, decision_id='B1', module=None):
        self.call('decision', {'decision_id': decision_id, 'decision': 'approved', 'module_id': module,
            'subject_sha256': digest({'plan': plan, 'registry': workflow.registry(self.state())}),
            'human_source_ref': self.ref(f'boundary-{decision_id}.txt', 'human approved this exact scope')},
            role='host', module=None)

    def test_boundary_review_required_but_clear_scope_needs_no_human_decision(self):
        plan = self.boundary_plan(); plan.pop('boundary_review')
        with self.assertRaisesRegex(Rejected, 'boundary review required'):
            self.accept_boundary_plan(plan)
        plan['boundary_review'] = {'issues': []}
        self.accept_boundary_plan(plan)
        self.assertFalse(self.state()['decisions'])

    def test_boundary_questions_require_global_human_approval_and_consume_it(self):
        plan = self.boundary_plan()
        with self.assertRaisesRegex(Rejected, 'human approval required'):
            self.accept_boundary_plan(plan)
        self.approve_boundaries(plan, 'WRONG', module='M001')
        with self.assertRaisesRegex(Rejected, 'human approval required'):
            self.accept_boundary_plan(plan, 'WRONG')
        self.approve_boundaries(plan)
        self.accept_boundary_plan(plan, 'B1')
        self.assertTrue(self.state()['decisions']['B1']['consumed'])
        with self.assertRaisesRegex(Rejected, 'human approval required'):
            self.accept_boundary_plan(plan, 'B1')

    def test_changed_scope_or_registry_invalidates_boundary_approval(self):
        plan = self.boundary_plan(); self.approve_boundaries(plan)
        changed = copy.deepcopy(plan)
        changed['boundary_review']['issues'][0]['proposed_resolution'] = 'Include guest access.'
        with self.assertRaisesRegex(Rejected, 'human approval required'):
            self.accept_boundary_plan(changed, 'B1')
        self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [],
                              'write_paths': [str(self.target / 'm2')]}, role='global-orchestrator', module=None)
        plan['requirement_owners']['R1'].append('M002')
        plan['case_owners']['C1'].append('M002')
        plan['boundary_review']['issues'][0].update(kind='cross-module', module_ids=['M001', 'M002'])
        with self.assertRaisesRegex(Rejected, 'human approval required'):
            self.accept_boundary_plan(plan, 'B1')
        self.approve_boundaries(plan, 'B2'); self.accept_boundary_plan(plan, 'B2')

    def test_boundary_review_rejects_unknown_module_and_duplicate_question(self):
        plan = self.boundary_plan()
        plan['boundary_review']['issues'][0]['module_ids'] = ['M999']
        with self.assertRaisesRegex(Rejected, 'unknown/duplicate boundary module'):
            self.accept_boundary_plan(plan)
        plan = self.boundary_plan()
        plan['boundary_review']['issues'].append(copy.deepcopy(plan['boundary_review']['issues'][0]))
        with self.assertRaisesRegex(Rejected, 'duplicate question_id'):
            self.accept_boundary_plan(plan)

    def test_green_module_acceptance_belongs_to_mo_without_extra_human_approval(self):
        self.prepare(); self.implementation()
        a, result = self.make_test_result(); self.submit(result, a)
        self.call('accept', {'assignment_id': a['assignment_id']})
        decisions = copy.deepcopy(self.state()['decisions'])
        payload = {'dod_ref': self.ref('green-dod.md', 'complete coverage reviewed')}
        for other in ('auditor', 'global-orchestrator', 'test-runner'):
            with self.assertRaisesRegex(Rejected, 'principal role denied'):
                self.call('complete', payload, role=other)
        self.call('complete', payload)
        self.assertEqual(self.state()['modules']['M001']['quality'], 'green-passed')
        self.assertEqual(self.state()['decisions'], decisions)
        for operation in ('audit', 'audit-verdict'):
            with self.assertRaisesRegex(Rejected, 'principal role denied'):
                self.call(operation, {}, module=None)

    def failed_module(self, category='code'):
        self.prepare(); self.implementation()
        a, r = self.make_test_result(quality='red-bug')
        r['paths'][0]['root_cause'].update(category=category, confidence='confirmed')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        return r

    def diagnose(self):
        self.call('diagnose', {'diagnosis_ref': self.ref(f'diag-{self.n}.md', 'root cause reviewed'), 'owner': 'M001',
                              'root_cause': {'category': 'code', 'summary': 'wrong result', 'confidence': 'confirmed',
                                             'owner': 'M001', 'next_action': 'fix'}}, role='diagnostician')
        self.call('diagnosis-accept')

    def defer(self, category='code'):
        self.call('audit-defer', {'root_cause': {'category': category, 'summary': 'requires shared resolution',
                                               'confidence': 'confirmed', 'owner': 'auditor', 'next_action': 'problem-audit'},
                                  'evidence_ref': self.ref(f'handoff-{self.n}.md', 'failure evidence')})

    def start_problem(self, aid='PA1'):
        self.call('problem-assign', {'assignment_id': aid, 'instance_id': 'auditor'}, role='global-orchestrator', module=None)

    def problem_report(self, aid='PA1', green=True, action=None):
        s = self.state(); a = workflow.problem_assignment(s, 'M001'); m = s['modules']['M001']
        adapter = self.base / f'problem-{aid}.py'
        adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n" +
                           "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':" + ('2' if green else '1') +
                           ",'passed':" + ('True' if green else 'False') + "}]},open(a.result_file,'w'))\n")
        rr = execute(self.root, 'M001', aid, 'P1', [sys.executable, str(adapter)], str(self.target), self.base / f'problem-exec-{aid}')
        receipt = json.loads(Path(rr['path']).read_text())
        previous = s.get('problem_results', {}).get('M001', m['results']).get('P1')
        root = {'category': 'code', 'summary': 'independent reproduction', 'confidence': 'confirmed', 'owner': 'M001', 'next_action': action or ('retry' if green else 'fix')}
        result = {'schema_version': 1, 'kind': 'tests', 'module_id': 'M001', 'run_id': 'demo',
                  'assignment_id': aid, 'actor_instance_id': 'auditor', 'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'],
                  'paths': [{'path_id': 'P1', 'quality': 'green-passed' if green else 'red-bug', 'executed': True,
                             'test_run_id': receipt['test_run_id'], 'execution_receipt': rr, 'root_cause': root,
                             'retest_of': previous['test_run_id'] if previous else None,
                             'assertions': json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']}]}
        return {'assignment_id': aid, 'snapshot': a['snapshot'], 'modules': [{'module_id': 'M001', 'result': result,
                    'root_cause': root, 'action': action or ('retry' if green else 'fix')}]}

    def submit_problem(self, report):
        self.call('problem-audit', {'report_ref': self.ref(f'problem-report-{self.n}.json', report)}, role='auditor', module=None)

    def test_global_coverage_blocks_implementation_and_rejects_missing_owners(self):
        p = self.plan(); self.call('plan', {'plan_ref': self.ref('p.json', p)}, role='spec-designer')
        self.approve(digest(p), 'D1'); self.call('freeze', {'decision_id': 'D1'})
        with self.assertRaises(Rejected): self.assign('implementer', 'I1')
        s = self.state()
        bad = {'global_spec': s['global_spec'], 'new_architecture': s['new_architecture'],
               'requirement_owners': {}, 'case_owners': {'C1': ['GLOBAL']}}
        with self.assertRaises(Rejected):
            self.call('global-plan', {'plan_ref': self.ref('bad-coverage.json', bad), 'review_ref': self.ref('review.md', 'review')}, role='global-orchestrator', module=None)
        self.global_plan(); self.assign('implementer', 'I1')

    def test_registry_change_requires_new_coverage_review(self):
        self.prepare()
        self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(self.target / 'm2')]}, role='global-orchestrator', module=None)
        with self.assertRaises(Rejected): self.assign('implementer', 'I1')
        self.global_plan(); self.assign('implementer', 'I1')

    def test_one_local_round_then_auditor_and_failed_memory(self):
        r = self.failed_module(); self.diagnose(); self.implementation('fixer', 'F1')
        a, r2 = self.make_test_result('TEST2', 'red-bug', r['paths'][0]['test_run_id'])
        self.submit(r2, a); self.call('accept', {'assignment_id': 'TEST2'})
        s = self.state()
        self.assertEqual(s['next_steps'][0]['operation'], 'audit-defer')
        self.assertEqual(s['modules']['M001']['fix_memory'][0]['status'], 'failed')
        self.assertFalse(s['modules']['M001']['fix_memory'][0]['reusable'])
        self.defer(); self.start_problem()
        self.assertEqual(self.state()['global_next_step']['operation'], 'problem-audit')

    def test_local_fix_resumes_the_implementer_session_first(self):
        self.failed_module()
        self.call('session', {'role': 'implementer', 'session_id': 'S-IMPL'})
        self.diagnose()
        step = self.state()['next_steps'][0]
        self.assertEqual((step['worker_role'], step['session_id'], step['session_affinity']), ('fixer', 'S-IMPL', 'implementer'))
        self.call('session', {'role': 'fixer', 'session_id': 'S-FIX'})
        step = self.state()['next_steps'][0]
        self.assertEqual(step['session_id'], 'S-FIX')
        self.assertNotIn('session_affinity', step)

    def test_host_reports_whether_it_followed_session_and_card_hints(self):
        self.failed_module()
        self.call('session', {'role': 'implementer', 'session_id': 'S-IMPL'})
        self.diagnose()
        step = self.state()['next_steps'][0]
        self.call('assign', {'assignment_id': 'F1', 'role': 'fixer', 'instance_id': 'fixer',
                             'session_id': 'S-OTHER', 'card_sha256': step['card_sha256']})
        hints = self.state()['modules']['M001']['assignments']['F1']['hints']
        self.assertEqual((hints['session_suggested'], hints['session_followed'], hints['card_followed']), ('S-IMPL', False, True))
        adoption = self.state()['hint_adoption']
        self.assertEqual(adoption['session']['not_followed'], 1)
        self.assertEqual(adoption['card']['followed'], 1)
        self.assertGreaterEqual(adoption['card']['unreported'], 2)  # earlier dispatches did not report

    def test_resumed_session_is_handed_only_sections_it_does_not_hold(self):
        self.prepare()
        self.call('session', {'role': 'implementer', 'session_id': 'S-IMPL'})
        self.assertNotIn('must_read_new', self.state()['next_steps'][0])  # nothing delivered yet: the full card applies
        plain = self.assign

        def assign(role, aid):
            step = self.state()['next_steps'][0]
            self.call('assign', {'assignment_id': aid, 'role': role, 'instance_id': role,
                                 'session_id': 'S-IMPL' if role == 'implementer' else 'S-OTHER', 'card_sha256': step['card_sha256']})
            return self.state()['modules']['M001']['assignments'][aid]
        self.assign = assign
        self.implementation()
        a, r = self.make_test_result(quality='red-bug')
        r['paths'][0]['root_cause'].update(category='code', confidence='confirmed')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.diagnose()
        step = self.state()['next_steps'][0]
        self.assertEqual((step['worker_role'], step['session_id']), ('fixer', 'S-IMPL'))
        keys = {reading.key(row) for row in step['must_read']}
        fresh = {reading.key(row) for row in step['must_read_new']}
        self.assertLess(fresh, keys)
        self.assertNotIn('AGENTS.md#四条红线', fresh)
        self.assertIn('Agents/fixer.md#', fresh)
        self.assertEqual(step['card_sha256'], reading.digest_card(step['must_read']))
        self.assign = plain

    def test_any_request_may_report_the_session_and_card_it_acted_on(self):
        self.prepare()
        self.call('session', {'role': 'module-orchestrator', 'session_id': 'S-MO'})
        plain = self.call

        def call(op, payload=None, **kw):
            if op != 'accept' or kw.get('request'):
                return plain(op, payload, **kw)
            step = self.state()['next_steps'][0]
            self.n += 1
            m = self.state()['modules']['M001']
            req = {'schema_version': 1, 'request_id': f'h{self.n}', 'run_id': 'demo', 'module_id': 'M001',
                   'expected_revision': m['revision'], 'operation': 'accept', 'payload': payload or {},
                   'hint': {'session_id': 'S-MO', 'card_sha256': step['card_sha256']}}
            return plain(op, payload, request=req)
        self.call = call
        self.implementation()
        m = self.state()['modules']['M001']
        self.assertIn('S-MO', m['delivered_cards'])
        self.assertEqual(m['card_load']['dispatches'], 1)
        self.assertEqual(m['card_load']['full'], m['card_load']['delivered'])
        a, r = self.make_test_result()
        self.submit(r, a)
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['session_id']), ('accept', 'S-MO'))
        self.assertEqual(step['must_read_new'], [])  # the same module-orchestrator card was already delivered
        self.call = plain
        with self.assertRaisesRegex(Rejected, 'hint needs'):
            self.call('accept', request={'schema_version': 1, 'request_id': 'bad', 'run_id': 'demo', 'module_id': 'M001',
                                         'expected_revision': self.state()['modules']['M001']['revision'], 'operation': 'accept',
                                         'payload': {}, 'hint': {'session_id': 'S-MO'}})
        cost = self.state()['workflow_cost']
        self.assertEqual(cost['modules']['M001']['card_dispatches'], 1)
        self.assertEqual(cost['totals']['card_bytes_delivered'], cost['totals']['card_bytes_full'])

    def test_assign_accepts_the_request_level_hint_too(self):
        self.prepare()
        step = self.state()['next_steps'][0]
        m = self.state()['modules']['M001']
        self.call('assign', request={'schema_version': 1, 'request_id': 'hinted-assign', 'run_id': 'demo', 'module_id': 'M001',
                                     'expected_revision': m['revision'], 'operation': 'assign',
                                     'payload': {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer'},
                                     'hint': {'session_id': 'S-IMPL', 'card_sha256': step['card_sha256']}})
        hints = self.state()['modules']['M001']['assignments']['I1']['hints']
        self.assertEqual((hints['session_used'], hints['card_followed']), ('S-IMPL', True))
        self.assertIn('S-IMPL', self.state()['modules']['M001']['delivered_cards'])

    def test_a_session_holding_too_much_protocol_text_is_advised_to_restart(self):
        self.prepare()
        self.call('session', {'role': 'implementer', 'session_id': 'S-IMPL'})
        self.assertNotIn('session_rotate', self.state()['next_steps'][0])
        plain = self.assign

        def assign(role, aid):
            step = self.state()['next_steps'][0]
            self.call('assign', {'assignment_id': aid, 'role': role, 'instance_id': role,
                                 'session_id': 'S-IMPL' if role == 'implementer' else 'S-OTHER', 'card_sha256': step['card_sha256']})
            return self.state()['modules']['M001']['assignments'][aid]
        self.assign = assign
        self.implementation()
        a, r = self.make_test_result(quality='red-bug')
        r['paths'][0]['root_cause'].update(category='code', confidence='confirmed')
        self.submit(r, a); self.call('accept', {'assignment_id': 'TEST1'})
        self.diagnose()
        self.assign = plain
        step = self.state()['next_steps'][0]
        self.assertEqual((step['worker_role'], step['session_id']), ('fixer', 'S-IMPL'))
        self.assertNotIn('session_rotate', step)  # one card is far below the budget
        with unittest.mock.patch.object(reading, 'ROTATE_BUDGET', 1000):
            step = self.state()['next_steps'][0]
        self.assertEqual(step['session_rotate']['reason'], 'reading-load')
        self.assertGreaterEqual(step['session_rotate']['delivered_bytes'], 1000)
        self.assertIn('must_read', step)  # advice only: the full card is still offered for a cold start

    def test_accepting_an_all_green_test_result_is_marked_mechanical(self):
        self.prepare(); self.implementation()
        a, result = self.make_test_result()
        self.assertNotIn('mechanical', self.state()['next_steps'][0])  # await-result: nothing submitted yet
        self.submit(result, a)
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['mechanical'], step['model_tier']), ('accept', True, 'low_cost'))
        self.call('accept', {'assignment_id': a['assignment_id']})  # still an MO event that re-validates the result

    def test_dispatching_a_worker_is_marked_mechanical(self):
        s = self.state(); s['test_design_required'] = True
        design = ledger.next_step(s, s['modules']['M001'])
        self.assertEqual((design['operation'], design['mode']), ('assign', 'design'))
        self.assertNotIn('mechanical', design)  # the module orchestrator writes the design input
        self.prepare()
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['worker_role'], step['mechanical']), ('assign', 'implementer', True))
        self.assertEqual(step['payload'], {'role': 'implementer'})
        self.implementation()
        step = self.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['worker_role'], step['mechanical']), ('assign', 'test-runner', True))
        self.assertEqual(step['payload'], {'role': 'test-runner'})
        # The host adds the ids it owns and submits as the module orchestrator; every assign guard still runs.
        self.call('assign', {**step['payload'], 'assignment_id': 'TEST1', 'instance_id': 'test-runner'})
        self.assertFalse(self.state()['modules']['M001']['assignments']['TEST1']['closed'])

    def test_a_mechanical_dispatch_names_the_worker_that_preflighted_the_stage(self):
        import test_context_readiness
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['ready'], step['mechanical']), ('assign', True, True))
        self.assertEqual(step['payload'], {'role': 'test-runner'})  # nobody has preflighted yet: the host names the instance
        ref = f.record(f.report('testing', instance='tester'))
        step = f.state()['next_steps'][0]
        self.assertEqual(step['mechanical'], True)
        self.assertEqual(step['payload'], {'role': 'test-runner', 'instance_id': 'tester', 'context_ref': ref})
        f.raw('assign', {**step['payload'], 'assignment_id': 'TEST1'})
        self.assertEqual(f.state()['modules']['M001']['assignments']['TEST1']['instance_id'], 'tester')

    def test_accepting_code_or_a_failing_result_is_not_mechanical(self):
        self.prepare()
        a = self.assign('implementer', 'I1')
        source = self.target / 'm1/code.py'; source.parent.mkdir(exist_ok=True); source.write_text('value = 2\n')
        refs = [file_ref(source)]
        from contracts import baseline
        self.submit({'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001', 'assignment_id': 'I1',
                     'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'], 'code_files': refs, 'code_baseline': baseline(refs),
                     'task_trace': [{'task_id': 'T1', 'files': [str(source)]}],
                     'production_binding_evidence': self.ref('binding.txt', 'real binding reviewed'),
                     'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': self.ref('diag.log', '0 errors')}}, a)
        step = self.state()['next_steps'][0]
        self.assertEqual(step['operation'], 'accept'); self.assertNotIn('mechanical', step)
        self.call('accept', {'assignment_id': 'I1'})
        a, result = self.make_test_result(quality='red-bug')
        result['paths'][0]['root_cause'].update(category='code', confidence='confirmed')
        self.submit(result, a)
        step = self.state()['next_steps'][0]
        self.assertEqual(step['operation'], 'accept'); self.assertNotIn('mechanical', step)

    def test_workflow_cost_counts_dispatches_receipts_and_repairs(self):
        self.failed_module(); self.diagnose(); self.implementation('fixer', 'F1')
        cost = self.state()['workflow_cost']
        row = cost['modules']['M001']
        self.assertEqual((row['dispatches'], row['fix_rounds'], row['human_decisions']), (3, 1, 1))
        self.assertEqual(cost['totals']['dispatches'], 3)
        report = (self.root / 'reports/migration-report.md').read_text()
        self.assertIn('## 流程成本', report)

    def test_peripheral_cause_skips_local_fix(self):
        self.failed_module('external')
        self.assertEqual(self.state()['next_steps'][0]['operation'], 'audit-defer')
        self.defer('external')
        self.assertEqual(self.state()['modules']['M001']['local_fix_used'], 0)
        self.assertEqual(self.state()['modules']['M001']['phase'], 'waiting-auditor')

    def test_problem_audit_green_requires_main_retest_and_final_audit(self):
        r = self.failed_module('external'); self.defer('external'); self.start_problem()
        with self.assertRaises(Rejected): self.call('invalidate', {'reason': 'audit locked'})
        report = self.problem_report()
        broken = copy.deepcopy(report); broken['modules'][0]['result']['paths'][0].pop('retest_of')
        with self.assertRaises(Rejected): self.submit_problem(broken)
        self.submit_problem(report)
        self.assertEqual(self.state()['modules']['M001']['phase'], 'waiting-auditor')
        self.call('audit-resume')
        with self.assertRaises(Rejected): self.call('complete', {})
        a, r2 = self.make_test_result('TEST2', previous=r['paths'][0]['test_run_id'])
        self.submit(r2, a); self.call('accept', {'assignment_id': 'TEST2'})
        self.call('complete', {'dod_ref': self.ref('dod.md', 'reviewed')})
        self.assertEqual(self.state()['quality'], 'yellow-blocked')
        self.assertEqual(self.state()['global_next_step']['operation'], 'audit-code-review')

    def test_a_human_disposition_names_the_subject_to_approve(self):
        self.failed_module('external'); self.defer('external'); self.start_problem()
        self.submit_problem(self.problem_report(green=False, action='human'))
        step = self.state()['next_steps'][0]
        resolution = self.state()['audit_resolutions']['M001']
        self.assertEqual((step['operation'], step['ready'], step['approval_subject_sha256']), ('audit-resume', False, digest(resolution)))
        self.approve(step['approval_subject_sha256'], 'DISPOSE')
        step = self.state()['next_steps'][0]
        self.assertEqual((step['ready'], step['payload']), (True, {'decision_id': 'DISPOSE'}))

    def test_problem_auditor_delegates_fix_and_memory_is_verified(self):
        r = self.failed_module('external'); self.defer('external'); self.start_problem()
        self.submit_problem(self.problem_report(green=False))
        with self.assertRaises(Rejected): self.call('audit-resume', role='auditor')
        self.call('audit-resume'); self.implementation('fixer', 'F1')
        a, r2 = self.make_test_result('TEST2', previous=r['paths'][0]['test_run_id'])
        self.submit(r2, a); self.call('accept', {'assignment_id': 'TEST2'})
        memory = self.state()['modules']['M001']['fix_memory'][0]
        self.assertTrue(memory['reusable']); self.assertEqual(memory['status'], 'verified')
        self.assertIn('regression_ref', memory); self.assertIn('fix_note_ref', memory)
        global_memory = json.loads((self.root / 'ledger/repair-memory.json').read_text())
        self.assertEqual(global_memory['entries'][0]['module_id'], 'M001')

    def test_precode_problem_report_stays_yellow(self):
        self.global_plan(); self.defer('tooling'); self.start_problem()
        s = self.state()
        report = {'assignment_id': 'PA1', 'snapshot': s['audit_assignment']['snapshot'], 'modules': [{
            'module_id': 'M001', 'quality': 'yellow-blocked', 'result': None, 'action': 'wait',
            'root_cause': s['audit_queue']['M001']['root_cause']}]}
        self.submit_problem(report)
        with self.assertRaises(Rejected): self.call('audit-resume')
        with self.assertRaises(Rejected):
            self.call('audit-assign', {'assignment_id': 'FINAL', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        self.assertEqual(self.state()['quality'], 'yellow-blocked')

    def test_openspec_views_rebuild_without_changing_frozen_definitions(self):
        self.prepare(); before = copy.deepcopy(self.state()['modules']['M001']['plan']['definitions'])
        change = self.root / 'openspec/changes/demo-m001'
        for relative in ('proposal.md', 'specs/m001/spec.md', 'design.md', 'tasks.md', 'status.md', 'checklist.md'):
            self.assertTrue((change / relative).is_file())
        self.implementation()
        self.assertIn('- [x] T1', (change / 'tasks.md').read_text())
        self.assertEqual(self.state()['modules']['M001']['plan']['definitions'], before)
        shutil.rmtree(change)
        self.state()
        self.assertTrue((change / 'status.md').exists())
        self.assertIn('- [x] T1', (change / 'tasks.md').read_text())
        self.assertEqual(json.loads((change / 'manifest.json').read_text())['validation'], 'structural-only')

    def test_openspec_rejects_invalid_delta_and_capability_escape(self):
        p = self.plan(); spec = next(d for d in p['definitions'] if d['kind'] == 'spec')
        spec['capability'] = '../../escape'
        with self.assertRaises(Rejected): self.call('plan', {'plan_ref': self.ref('escape.json', p)}, role='spec-designer')
        spec.pop('capability'); spec.update(self.ref('invalid-spec.md', 'not a delta'))
        with self.assertRaises(Rejected): self.call('plan', {'plan_ref': self.ref('invalid.json', p)}, role='spec-designer')

    def test_task_projection_requires_matching_definition_ids(self):
        p = self.plan()
        task = next(d for d in p['definitions'] if d['kind'] == 'tasks')
        task.update(self.ref('unmapped-tasks.md', '- [ ] OTHER unrelated task'))
        with self.assertRaises(Rejected): self.call('plan', {'plan_ref': self.ref('unmapped-plan.json', p)}, role='spec-designer')

    def test_dependency_change_preserves_queued_consumer(self):
        self.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'],
                              'write_paths': [str(self.target / 'm2')]}, role='global-orchestrator', module=None)
        self.prepare()
        self.call('audit-defer', {'root_cause': {'category': 'dependency', 'summary': 'producer required',
                                               'confidence': 'confirmed', 'owner': 'M001', 'next_action': 'problem-audit'},
                                  'evidence_ref': self.ref('consumer.md', 'waiting on producer')}, module='M002')
        self.implementation()
        state = self.state()
        self.assertEqual(state['modules']['M002']['phase'], 'waiting-auditor')
        self.assertIn('M002', state['audit_queue'])
        self.assertFalse(state['global_next_step']['ready'])
        self.assertEqual(state['global_next_step']['reason'], 'await-all-module-rounds')

    def test_repairable_code_cannot_skip_first_local_round(self):
        self.failed_module()
        with self.assertRaises(Rejected): self.defer('code')
        self.assertEqual(self.state()['next_steps'][0]['operation'], 'diagnose')
