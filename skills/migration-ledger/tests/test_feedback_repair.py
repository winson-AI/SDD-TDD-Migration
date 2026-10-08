"""Execution-feedback routing and proven task isolation through real Ledger events."""
import copy
import json
import sys
import unittest
from pathlib import Path

import control_policy
import ledger
import task_revalidation
import test_validation as tv
from contracts import Rejected, baseline, check_ref, file_ref
from execute_test import execute
import test_control_policy
import migration_report
import reading


class FeedbackRepairTests(unittest.TestCase):
    def setUp(self):
        self.t = test_control_policy.ControlPolicyTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def coded_failure(self):
        f = self.f; self.t.freeze(); f.implementation()
        a, r = f.make_test_result(quality='red-bug'); f.submit(r, a)
        f.call('accept', {'assignment_id': a['assignment_id']})

    def diagnose(self, category, **extra):
        f = self.f
        f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis.md', category), 'owner': 'module-orchestrator',
                           'root_cause': {'category': category}, **extra}, role='diagnostician')

    def test_code_error_routes_to_fixer_without_spec_planning(self):
        self.coded_failure(); self.diagnose('code')
        self.assertEqual(self.f.state()['next_steps'][0]['operation'], 'diagnosis-accept')
        self.f.call('diagnosis-accept')
        self.assertEqual(self.f.state()['next_steps'][0]['worker_role'], 'fixer')

    def test_planning_dependency_function_and_fidelity_gaps_route_to_cr(self):
        self.coded_failure()
        for category in ('spec', 'planning-gap', 'dependency-gap', 'function-gap', 'fidelity-gap'):
            with self.subTest(category=category):
                self.diagnose(category)
                step = self.f.state()['next_steps'][0]
                self.assertEqual(step['operation'], 'change')
                self.assertNotIn('then_assign', step)
        old = self.f.state()['modules']['M001']['code_files']
        self.f.call('change', self.f.state()['next_steps'][0]['payload'])
        self.assertEqual(self.f.state()['next_steps'][0]['operation'], 'plan')
        self.assertEqual(self.f.state()['modules']['M001']['code_files'], old)
        self.assertEqual(self.f.state()['run_id'], 'demo')

    def test_scope_gap_routes_upstream_and_cannot_be_dispatched_as_fixer(self):
        self.coded_failure(); self.diagnose('scope-insufficient')
        self.assertEqual(self.f.state()['next_steps'][0]['operation'], 'realloc-request')
        self.f.call('diagnosis-accept')
        step = self.f.state()['next_steps'][0]
        self.assertEqual(step['operation'], 'realloc-request')
        with self.assertRaisesRegex(Rejected, 'CR/upstream'):
            self.f.assign('fixer', 'WRONG')
        self.f.call('realloc-request', step['payload'])
        self.assertEqual(self.f.state()['modules']['M001']['phase'], 'waiting-upstream')

    def test_planning_gap_cannot_be_labelled_as_code_only(self):
        with self.assertRaisesRegex(Rejected, 'cannot route'):
            control_policy.repair_route({'root_cause': 'planning-gap', 'repair_route': 'fixer'})
        with self.assertRaisesRegex(Rejected, 'upstream allocation'):
            control_policy.repair_route({'root_cause': 'scope-insufficient', 'repair_route': 'spec'})

    def test_worker_cannot_submit_a_fabricated_reuse_marker(self):
        self.t.freeze(); self.f.implementation()
        a, r = self.f.make_test_result()
        r['paths'][0]['validation_reuse'] = {'valid_for_baseline': a['code_baseline']}
        with self.assertRaisesRegex(Rejected, 'Ledger-owned'): self.f.submit(r, a)


class TaskIndependenceTests(unittest.TestCase):
    setUp = FeedbackRepairTests.setUp
    def plan(self):
        f = self.f; p = self.t.two_tasks()
        second = copy.deepcopy(p['paths'][0]); second.update(path_id='P2', kind='automation')
        p['paths'][0]['kind'] = 'automation'; p['paths'].append(second)
        for tid, pid, directory in [('T1', 'P1', 'first'), ('T2', 'P2', 'second')]:
            task = next(t for t in p['tasks'] if t['task_id'] == tid)
            task.update(path_ids=[pid, 'B'], scope={'write_paths': [str(f.target / 'm1' / directory)]})
        p['paths'].append({'path_id': 'B', 'case_id': 'C1', 'requirement_id': 'R1', 'kind': 'build', 'name': 'build',
            'expected_assertions': [{'assertion_id': 'BUILD', 'expected': 0}],
            'command': {'argv': [sys.executable, '-c', 'pass'], 'cwd': str(f.target), 'timeout_seconds': 10,
                        'selection_ref': f.ref('selection.md', 'Build entire module')}})
        return p

    def implement(self, tids, aid, value=2):
        f = self.f; m = f.state()['modules']['M001']
        tasks = [t for t in m['plan']['tasks'] if t['task_id'] in tids]
        f.call('assign', {'assignment_id': aid, 'role': 'implementer', 'instance_id': 'implementer',
                         'task_ids': tids, 'path_ids': sorted({pid for t in tasks for pid in t['path_ids']})})
        a = f.state()['modules']['M001']['assignments'][aid]
        refs = {r['path']: r for r in m['code_files']}; trace = []
        for task in tasks:
            code = Path(task['scope']['write_paths'][0]) / 'code.py'
            code.parent.mkdir(parents=True, exist_ok=True); code.write_text(f'value = {value}\n')
            ref = file_ref(code); refs[ref['path']] = ref
            trace.append({'task_id': task['task_id'], 'files': [str(code)]})
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
            'assignment_id': aid, 'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'],
            'code_files': list(refs.values()), 'code_baseline': baseline(list(refs.values())), 'task_trace': trace,
            'production_binding_evidence': f.ref('binding-'+aid+'.md', 'Source behavior bound to production'),
            'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref(aid+'.log', '0 errors')}}
        f.submit(result, a); f.call('accept', {'assignment_id': aid})

    def execute_paths(self, aid, scope, ids, red=None):
        f = self.f; m = f.state()['modules']['M001']
        f.call('assign', {'assignment_id': aid, 'role': 'test-runner', 'instance_id': 'test-runner',
                         'test_scope': scope, 'task_ids': ['T1', 'T2'], 'path_ids': ids})
        a = f.state()['modules']['M001']['assignments'][aid]; rows = []
        for pid in ids:
            path = next(p for p in m['plan']['paths'] if p['path_id'] == pid)
            if pid == 'B': argv = path['command']['argv']
            else:
                task = next(t for t in m['plan']['tasks'] if pid in t['path_ids'])
                code = str(Path(task['scope']['write_paths'][0]) / 'code.py')
                script = f.base / (aid+'-'+pid+'.py')
                script.write_text('import argparse,json,runpy\np=argparse.ArgumentParser();p.add_argument("--query-file");'
                    'p.add_argument("--result-file");a=p.parse_args();'
                    f'v=runpy.run_path({code!r})["value"];'
                    'json.dump({"assertions":[{"assertion_id":"A1","expected":2,"actual":v,"passed":v==2}]},open(a.result_file,"w"))')
                argv = [sys.executable, str(script)]
            ref = execute(f.root, 'M001', aid, pid, argv, str(f.target), f.base / ('exec-'+aid+'-'+pid))
            receipt = json.loads(check_ref(ref).read_text())
            if pid == 'B': assertions = [{'assertion_id': 'BUILD', 'expected': 0, 'actual': receipt['exit_code'], 'passed': receipt['exit_code'] == 0}]
            else: assertions = json.loads(check_ref(receipt['result_ref']).read_text())['assertions']
            row = {'path_id': pid, 'quality': 'red-bug' if pid == red else 'green-passed', 'executed': True,
                   'execution_receipt': ref, 'test_run_id': receipt['test_run_id'], 'assertions': assertions,
                   'retest_of': m['results'].get(pid, {}).get('test_run_id')}
            if pid == red:
                row['root_cause'] = {'category': 'code', 'summary': 'Observed failure', 'confidence': 'confirmed',
                                     'owner': 'M001', 'next_action': 'repair'}
            rows.append(row)
        f.submit({'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'M001',
                  'assignment_id': aid, 'actor_instance_id': 'test-runner', 'freeze_id': a['freeze_id'],
                  'code_baseline': a['code_baseline'], 'paths': rows}, a)
        f.call('accept', {'assignment_id': aid})

    def prepared(self):
        self.t.freeze(self.plan()); self.implement(['T1'], 'I1', value=1); self.implement(['T2'], 'I2')
        self.execute_paths('BUILD1', 'build', ['B']); self.execute_paths('TEST1', 'automation', ['P1', 'P2'], red='P1')

    def revise(self, edit=None, proof_edit=None, proof=True):
        f = self.f; old = f.state()['modules']['M001']; p = copy.deepcopy(old['plan'])
        p['tasks'][0]['name'] = 'Update T1 fidelity implementation guidance '+str(f.n)
        if edit: edit(p)
        f.call('change', {'request_ref': f.ref('cr.md', 'T1 planning gap'), 'impact_ref': f.ref('impact.md', 'Review affected task')})
        f.call('plan', {'plan_ref': f.ref('new-plan-'+str(f.n)+'.json', p)}, role='spec-designer')
        step = f.state()['next_steps'][0]
        self.assertIn('template/task-independence.json', step['templates'])
        self.assertLessEqual(sum((reading.PACKAGE / name).stat().st_size for name in step['templates']), reading.TRIGGERED_TEMPLATE_BUDGET)
        doc = {'schema_version': 1, 'from_freeze_id': old['freeze_id'], 'to_plan_hash': f.state()['modules']['M001']['plan_hash'],
               'reviewer_instance_id': 'module-orchestrator', 'affected_task_ids': ['T1'], 'unchanged_task_ids': ['T2'],
               'tasks': [{'task_id': tid, 'depends_on': [], 'input_refs': [],
                          'evidence_refs': [f.ref('isolation-'+tid+'.md', 'Independent source behavior, runtime, fixtures and resource inputs reviewed')]} for tid in ('T1', 'T2')]}
        if proof_edit: proof_edit(doc)
        extra = {'task_independence_ref': f.ref('independence-'+str(f.n)+'.json', doc)} if proof else {}
        review = self.t.review(**extra)
        f.call('plan-review', {'review_ref': review})
        f.call('freeze', f.state()['next_steps'][0]['payload'])
        return old

    def test_independent_task_keeps_code_and_green_receipt_only_affected_path_retests(self):
        self.prepared(); old = self.revise(); f = self.f; m = f.state()['modules']['M001']
        self.assertEqual(m['accepted_task_ids'], ['T2']); self.assertEqual(m['task_revalidation']['mode'], 'partial')
        self.assertEqual(f.state()['next_steps'][0]['payload']['task_ids'], ['T1'])
        self.assertEqual(set(f.state()['next_steps'][0]['payload']['path_ids']), {'B', 'P1'})
        self.assertTrue(m['results']['P1']['stale']); self.assertTrue(m['results']['B']['stale'])
        self.assertFalse(m['results']['P2']['stale'])
        self.implement(['T1'], 'UPDATE')
        m = f.state()['modules']['M001']; self.assertFalse(tv.build_ready(m))
        self.assertEqual(m['results']['P2']['code_baseline'], old['code_baseline'])
        self.assertEqual(m['results']['P2']['test_run_id'], old['results']['P2']['test_run_id'])
        self.assertTrue(tv.path_green(m, 'P2')); self.assertNotEqual(m['code_baseline'], old['code_baseline'])
        with self.assertRaisesRegex(Rejected, 'build'):
            f.call('assign', {'assignment_id': 'EARLY', 'role': 'test-runner', 'instance_id': 'test-runner',
                             'test_scope': 'automation', 'task_ids': ['T1'], 'path_ids': ['P1']})
        self.execute_paths('BUILD2', 'build', ['B'])
        self.assertEqual(f.state()['next_steps'][0]['payload']['path_ids'], ['P1'])
        self.execute_paths('RETEST', 'automation', ['P1'])
        m = f.state()['modules']['M001']; self.assertEqual(m['phase'], 'dod'); self.assertTrue(tv.all_green(m))
        summary = migration_report.build(f.root, f.state(), 0)['automation']
        self.assertEqual(summary['passed_paths'], 2)
        self.assertEqual(summary['reused_passed_paths'], 1)
        self.assertEqual(summary['current_executed_paths'], 1)
        self.assertTrue(summary['modules']['M001']['validation_complete'])
        self.assertFalse(summary['validation_complete'])  # GLOBAL path still awaits unified audit.
        self.assertEqual(summary['tasks']['M001/T2']['passed_paths'], 1)

    def test_no_proof_falls_back_to_full_module(self):
        self.prepared(); self.revise(proof=False)
        m = self.f.state()['modules']['M001']
        self.assertEqual(m['accepted_task_ids'], []); self.assertTrue(all(r['stale'] for r in m['results'].values()))

    def test_shared_writer_dependency_path_and_changed_spec_fall_back(self):
        variants = [
            (lambda p: p['tasks'][0]['scope'].update(write_paths=[str(self.f.target / 'm1')]), None),
            (None, lambda d: d['tasks'][1].update(depends_on=['T1'])),
            (None, lambda d: d['tasks'][1].update(input_refs=[self.f.state()['modules']['M001']['code_files'][0]])),
            (lambda p: p['tasks'][0]['path_ids'].append('P2'), None),
            (lambda p: p['definitions'].__setitem__(1, {**self.f.ref('extra-spec.md', '## ADDED Requirements\n### Requirement: R1\nChanged behavior\n#### Scenario: altered\nWHEN invoked THEN altered\n'), 'kind': 'spec'}), None),
        ]
        for edit, proof_edit in variants:
            with self.subTest(edit=edit, proof_edit=proof_edit):
                if self.f.state()['modules']['M001']['plan']: self.doCleanups(); self.setUp()
                self.prepared(); self.revise(edit, proof_edit)
                self.assertEqual(self.f.state()['modules']['M001']['task_revalidation']['mode'], 'full')

    def test_stale_proof_and_unreported_changed_task_are_rejected(self):
        self.prepared()
        with self.assertRaisesRegex(Rejected, 'proof stale'):
            self.revise(proof_edit=lambda d: d.update(to_plan_hash='0'*64))

    def test_unreported_task_change_cannot_preserve_its_acceptance(self):
        self.prepared()
        with self.assertRaisesRegex(Rejected, 'omits changed TASK'):
            self.revise(edit=lambda p: p['tasks'][1].update(name='Changed T2'))

    def test_repeated_local_cr_keeps_original_independent_execution_provenance(self):
        self.prepared(); original = self.revise(); self.implement(['T1'], 'UPDATE1')
        self.execute_paths('BUILD2', 'build', ['B']); self.execute_paths('RETEST1', 'automation', ['P1'])
        self.revise(); self.implement(['T1'], 'UPDATE2')
        self.execute_paths('BUILD3', 'build', ['B']); self.execute_paths('RETEST2', 'automation', ['P1'])
        m = self.f.state()['modules']['M001']
        self.assertTrue(tv.all_green(m)); self.assertEqual(len(m['change_request_history']), 2)
        self.assertEqual(m['results']['P2']['test_run_id'], original['results']['P2']['test_run_id'])

    def test_non_green_independent_path_is_never_carried_as_success(self):
        self.prepared()
        # A non-Green record must never be promoted by independence metadata.
        m = self.f.state()['modules']['M001']
        m['results']['P2'].update(quality='red-bug', stale=False)
        m['change_request'] = {'from_freeze_id': m['freeze_id'], 'previous_plan': {'plan': copy.deepcopy(m['plan']), 'plan_hash': m['plan_hash']}}
        proof = {'schema_version': 1, 'from_freeze_id': m['freeze_id'], 'to_plan_hash': m['plan_hash'],
                 'reviewer_instance_id': 'module-orchestrator', 'affected_task_ids': ['T1'], 'unchanged_task_ids': ['T2'],
                 'tasks': [{'task_id': tid, 'depends_on': [], 'input_refs': [], 'evidence_refs': [self.f.ref('proof-'+tid, 'isolation')]} for tid in ('T1', 'T2')]}
        ref = self.t.review(task_independence_ref=self.f.ref('proof.json', proof))
        result = task_revalidation.prepare(m, ref)
        self.assertEqual(result['retained_path_ids'], [])

    def test_protected_resource_change_invalidates_reuse(self):
        self.prepared(); resource = self.f.target / 'shared-icon.txt'; resource.write_text('original')
        self.revise(proof_edit=lambda d: d['tasks'][1].update(input_refs=[file_ref(resource)]))
        resource.write_text('changed')
        m = self.f.state()['modules']['M001']
        self.assertEqual(m['effective_quality'], 'yellow-blocked')
        with self.assertRaises((Rejected, OSError)): task_revalidation.current(m)

    def test_active_affected_worker_cannot_hide_a_retained_task_change(self):
        self.prepared(); self.revise(); f = self.f
        step = f.state()['next_steps'][0]
        f.call('assign', {**step['payload'], 'assignment_id': 'UPDATE', 'instance_id': 'implementer'})
        (f.target / 'm1/first/code.py').write_text('value = 2\n')
        self.assertNotIn('effective_quality', f.state()['modules']['M001'])
        (f.target / 'm1/second/code.py').write_text('value = 99\n')
        self.assertEqual(f.state()['modules']['M001']['effective_quality'], 'yellow-blocked')


if __name__ == '__main__': unittest.main()
