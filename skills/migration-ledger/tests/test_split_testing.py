"""Build-first validation, explicit automation omissions, dependency progress and recovery."""
import test_ledger
import copy
from pathlib import Path
import sys
import unittest

import test_context_readiness as context_fixture
from contracts import Rejected, read_json
from execute_test import execute
import test_validation as tv

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
from harmony_stage import build as stage_result
from discover_build import discover


class SplitTestingTests(unittest.TestCase):
    def setUp(self):
        self.f = f = context_fixture.ContextReadinessTests()
        f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state()
        f.root = f.base / 'split-run'
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids',
                 'global_spec', 'new_architecture', 'global_paths')}, 'dimension_slicing_required': False, 'split_testing_required': True}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm1')]},
               role='global-orchestrator', module=None)
        self.build_code = 'raise SystemExit(0)'
        old_plan, old_report, old_call = f.plan, f.report, f.call
        def plan():
            p = old_plan(); p['paths'][0]['kind'] = 'automation'
            p['paths'].append({'path_id': 'B1', 'kind': 'build', 'name': 'compile', 'case_id': 'C1',
                'requirement_id': 'R1', 'required': True,
                'expected_assertions': [{'assertion_id': 'BUILD-EXIT', 'expected': 0}],
                'command': {'argv': [sys.executable, '-c', self.build_code], 'cwd': str(f.target), 'timeout_seconds': 20,
                            'selection_ref': f.ref('build-selection.md', 'Fixture compile-only command, chosen for target module')}})
            p['tasks'][0]['path_ids'].append('B1')
            return p
        def report(stage, module='M001', instance=None, draft=None, blocked=None):
            r = old_report(stage, module, instance, draft, blocked)
            if stage == 'building':
                command = f.state()['modules'][module]['plan']['paths'][1]['command']
                r['execution'] = {**command, 'environment_ref': f.ref('build-env.md', 'Python build fixture')}
            return r
        def call(op, payload=None, **kwargs):
            payload = copy.deepcopy(payload or {})
            if op == 'assign' and payload.get('role') == 'test-runner':
                m = f.state()['modules'][kwargs.get('module', 'M001')]
                payload.setdefault('test_scope', 'automation' if tv.build_ready(m) else 'build')
            return old_call(op, payload, **kwargs)
        f.plan, f.report, f.call = plan, report, call

    def prepare(self):
        self.f.prepare(); self.f.implementation()

    def compile(self, aid='BUILD1'):
        f = self.f
        assignment = f.assign('test-runner', aid)
        command = f.state()['modules']['M001']['plan']['paths'][1]['command']
        receipt = execute(f.root, 'M001', aid, 'B1', command['argv'], command['cwd'], f.base / aid)
        result = stage_result(f.root, 'M001', aid, [receipt])
        f.submit(result, assignment); f.call('accept', {'assignment_id': aid})
        return result

    def defer(self):
        f = self.f
        report = f.record(f.report('testing', blocked='test-environment'))
        f.raw('automation-unavailable', {'context_ref': report})
        return report

    def test_build_then_automation_then_dod(self):
        f = self.f; self.prepare()
        self.assertEqual(f.state()['next_steps'][0]['test_scope'], 'build')
        self.compile()
        self.assertEqual(f.state()['next_steps'][0]['test_scope'], 'automation')
        self.assertEqual(f.state()['modules']['M001']['phase'], 'testing')
        a, r = f.make_test_result(); f.submit(r, a); f.call('accept', {'assignment_id': a['assignment_id']})
        f.call('complete', {'dod_ref': f.ref('dod.md', 'build and all cases passed'), 'checks_passed': True})
        self.assertEqual(f.state()['modules']['M001']['quality'], 'green-passed')
        self.assertEqual(set(f.state()['modules']['M001']['results']), {'B1', 'P1'})

    def test_build_only_case_cannot_count_as_automation_coverage(self):
        plan = self.f.plan()
        plan['paths'][1]['case_id'] = 'BUILD-ONLY-CASE'
        with self.assertRaisesRegex(Rejected, 'every module case needs an automation path'):
            tv.plan_check(plan, self.f.target)
        path = copy.deepcopy(plan['paths'][0])
        path.update(path_id='P2', case_id='BUILD-ONLY-CASE')
        plan['paths'].append(path)
        tv.plan_check(plan, self.f.target)

    def test_automation_cannot_run_before_build_or_conceal_compile_failure(self):
        f = self.f; self.prepare()
        ref = f.record(f.report('testing'))
        with self.assertRaisesRegex(Rejected, 'build must precede'):
            f.raw('assign', {'assignment_id': 'EARLY', 'role': 'test-runner', 'instance_id': 'test-runner',
                             'test_scope': 'automation', 'context_ref': ref})
        with self.assertRaisesRegex(Rejected, 'current build'):
            self.defer()

    def repair_build(self):
        f = self.f
        self.build_code = "from pathlib import Path; raise SystemExit(0 if '3' in Path('m1/code.py').read_text() else 1)"
        self.prepare(); self.compile()
        self.assertEqual(f.state()['modules']['M001']['results']['B1']['quality'], 'red-bug')
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'diagnose')
        cause = {'category': 'code', 'summary': 'compile fixture rejects old implementation', 'confidence': 'confirmed',
                 'owner': 'M001', 'next_action': 'fix'}
        f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis.md', 'Compiler log and source show cause'),
                           'owner': 'M001', 'root_cause': cause}, role='diagnostician')
        f.call('diagnosis-accept')
        self.assertEqual(f.state()['next_steps'][0]['worker_role'], 'fixer')
        f.implementation('fixer', 'FIX1')
        m = f.state()['modules']['M001']
        self.assertIsNone(m['build_baseline'])
        self.assertTrue(m['stale'])
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['test_scope']), ('assign', 'build'))
        self.assertEqual(step['context_gate']['stage'], 'building')
        self.compile('BUILD2')
        self.assertEqual(f.state()['modules']['M001']['fix_rounds_used'], 1)
        self.assertEqual(f.state()['modules']['M001']['results']['B1']['quality'], 'green-passed')
        self.assertEqual(f.state()['next_steps'][0]['test_scope'], 'automation')

    def test_build_red_enters_fixer_then_rebuild(self):
        f = self.f; self.repair_build()
        step = f.state()['next_steps'][0]
        self.assertEqual(step['context_gate']['stage'], 'testing')
        self.assertFalse(step['ready'])  # A fresh automation preflight is still required.
        memory = f.state()['modules']['M001']['fix_memory'][0]
        self.assertEqual(memory['status'], 'awaiting-regression')
        self.assertFalse(memory['reusable'])
        a, result = f.make_test_result()
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'dod')
        self.assertTrue(m['fix_memory'][0]['reusable'])
        self.assertTrue(m['results']['B1']['retest_of'])
        f.call('complete', {'dod_ref': f.ref('dod.md', 'Rebuilt current code and verified all paths'), 'checks_passed': True})
        self.assertEqual(f.state()['modules']['M001']['quality'], 'green-passed')

    def test_build_repair_and_automation_share_one_local_round(self):
        f = self.f; self.repair_build()
        a, result = f.make_test_result(quality='red-bug')
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        s = f.state()
        self.assertEqual(s['modules']['M001']['local_fix_used'], 1)
        self.assertEqual(s['modules']['M001']['fix_memory'][0]['status'], 'failed')
        self.assertEqual(s['next_steps'][0]['operation'], 'audit-defer')
        self.assertEqual(s['next_steps'][0]['root_cause']['category'], 'local-round-exhausted')

    def test_build_process_success_requires_accept_and_separate_testing_context(self):
        f = self.f; self.prepare()
        a = f.assign('test-runner', 'BUILD1')
        command = f.state()['modules']['M001']['plan']['paths'][1]['command']
        receipt = execute(f.root, 'M001', 'BUILD1', 'B1', command['argv'], command['cwd'], f.base / 'BUILD1')
        f.submit(stage_result(f.root, 'M001', 'BUILD1', [receipt]), a)
        self.assertFalse(tv.build_ready(f.state()['modules']['M001']))
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'accept')
        f.call('accept', {'assignment_id': 'BUILD1'})
        self.assertTrue(tv.build_ready(f.state()['modules']['M001']))
        wrong_context = f.record(f.report('building'))
        with self.assertRaises(Rejected):
            f.raw('assign', {'assignment_id': 'WRONG-CONTEXT', 'role': 'test-runner',
                            'instance_id': 'test-runner', 'test_scope': 'automation', 'context_ref': wrong_context})

    def test_environment_omission_settles_without_green_or_human_gate(self):
        f = self.f; self.prepare(); self.compile(); self.defer()
        s = f.state(); m = s['modules']['M001']
        self.assertEqual(m['phase'], 'automation-deferred')
        self.assertEqual(m['quality'], 'yellow-blocked')
        self.assertFalse(m['results']['P1']['executed'])
        self.assertEqual(m['results']['B1']['quality'], 'green-passed')
        self.assertEqual(m['fix_rounds_used'], 0)
        self.assertTrue(s['module_rounds']['all_settled'])
        self.assertEqual(s['global_next_step']['operation'], 'audit-code-review')
        test_ledger.code_review(f)
        with self.assertRaises(Rejected):
            f.call('complete', {'dod_ref': f.ref('false-dod.md', 'not tested'), 'checks_passed': True})
        report = f.record(f.report('audit-testing', module=None, instance='auditor', blocked='test-environment'))
        f.raw('audit-unavailable', {'context_ref': report}, role='auditor', module=None)
        s = f.state()
        self.assertEqual(s['global_next_step']['reason'], 'completed-with-unverified-tests')
        self.assertEqual(s['quality'], 'yellow-blocked')
        self.assertTrue(all(not p['executed'] for p in s['audit']['paths']))

    def test_environment_restoration_retests_without_human_approval(self):
        f = self.f; self.prepare(); self.compile(); self.defer()
        old = f.state()['modules']['M001']['results']['P1']['test_run_id']
        ref = f.record(f.report('testing'))
        f.raw('automation-resume', {'context_ref': ref})
        a, r = f.make_test_result(previous=old)
        f.submit(r, a); f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')
        self.assertEqual(f.state()['modules']['M001']['results']['P1']['retest_of'], old)

    def test_omission_cannot_hide_business_failure_or_non_environment_blocker(self):
        f = self.f; self.prepare(); self.compile()
        ref = f.record(f.report('testing', blocked='provider-binding'))
        with self.assertRaisesRegex(Rejected, 'only automation environment'):
            f.raw('automation-unavailable', {'context_ref': ref})
        a, r = f.make_test_result(quality='red-bug'); f.submit(r, a); f.call('accept', {'assignment_id': a['assignment_id']})
        with self.assertRaisesRegex(Rejected, 'cannot conceal'):
            self.defer()

    def test_deferred_provider_does_not_block_actual_downstream(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'dependencies': ['M001'],
                           'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        self.prepare(); self.compile(); self.defer()
        f.call('dependency-ready', role='global-orchestrator', module='M002')
        f.call('resume', module='M002')
        # Compile a consumer plan in the same real Ledger; no direct state mutations.
        plan = f.plan(); plan['module_id'] = 'M002'
        for path in plan['paths']: path['path_id'] += '-M2'
        plan['tasks'][0]['path_ids'] = [p['path_id'] for p in plan['paths']]
        f.call('plan', {'plan_ref': f.ref('consumer.json', plan)}, role='spec-designer', module='M002')
        from contracts import digest
        f.call('decision', {'decision_id': 'D2', 'module_id': 'M002', 'decision': 'approved',
                           'subject_sha256': digest(plan), 'human_source_ref': f.ref('approval2.md', 'Approved consumer')},
               role='host', module=None)
        f.call('freeze', {'decision_id': 'D2'}, module='M002')
        f.call('assign', {'assignment_id': 'CONSUMER', 'role': 'implementer', 'instance_id': 'consumer'}, module='M002')
        self.assertEqual(f.state()['modules']['M002']['phase'], 'implementing')
        self.assertEqual(f.state()['modules']['M001']['quality'], 'yellow-blocked')

    def run_final_audit(self, actual=2):
        f = self.f; self.prepare(); self.compile(); self.defer()
        adapter = f.base / 'adapter.py'
        adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args();json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':2,'passed':True}]},open(a.result_file,'w'))")
        adapter.write_text(adapter.read_text().replace("'actual':2,'passed':True", f"'actual':{actual},'passed':{actual == 2}"))
        test_ledger.code_review(f)
        report = f.report('audit-testing', module=None, instance='auditor')
        command = f.state()['modules']['M001']['plan']['paths'][1]['command']
        report['execution']['commands'] = {'B1': {'argv': command['argv'], 'cwd': command['cwd']}}
        ref = f.record(report)
        f.raw('audit-assign', {'assignment_id': 'FINAL', 'instance_id': 'auditor', 'context_ref': ref}, role='global-orchestrator', module=None)
        import ledger
        scope = ledger.audit_scope(f.state()); rows = []
        for path in scope['plan']['paths']:
            argv = command['argv'] if path['path_id'] == 'B1' else report['execution']['argv']
            rr = execute(f.root, 'GLOBAL', 'FINAL', path['path_id'], argv, str(f.target), f.base / ('audit-'+path['path_id']))
            receipt = read_json(rr['path']); captured = read_json(receipt['result_ref']['path'])
            rows.append({'path_id': path['path_id'], 'quality': 'green-passed' if all(a['passed'] for a in captured['assertions']) else 'red-bug', 'executed': True,
                         'root_cause': {'category': 'code', 'summary': 'Observed assertion mismatch', 'confidence': 'confirmed', 'owner': 'M001', 'next_action': 'fix'},
                         'test_run_id': receipt['test_run_id'], 'assertions': captured['assertions'], 'execution_receipt': rr,
                         'retest_of': scope['results'].get(path['path_id'], {}).get('test_run_id')})
        result = {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL',
                  'assignment_id': 'FINAL', 'actor_instance_id': 'auditor', 'freeze_id': scope['freeze_id'],
                  'code_baseline': scope['code_baseline'], 'snapshot': {'M001': f.state()['modules']['M001']['code_baseline']}, 'paths': rows}
        f.raw('audit', {'report_ref': f.ref('final.json', result)}, role='auditor', module=None)
        return f

    def test_empty_global_audits_only_yellow_preserving_passed_build(self):
        f = self.f; original = f.state(); f.root = f.base / 'empty-global-run'
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids',
                 'global_spec', 'new_architecture')}, 'global_paths': [], 'dimension_slicing_required': False, 'split_testing_required': True}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm1')]},
               role='global-orchestrator', module=None)
        self.run_final_audit()
        s = f.state()
        self.assertEqual(s['audit_assignment']['path_ids'], ['P1'])
        self.assertEqual([r['path_id'] for r in s['audit']['paths']], ['P1'])
        build = s['modules']['M001']['results']['B1']
        self.assertEqual(build['quality'], 'green-passed')
        self.assertNotIn('module_retest_of', build)
        self.assertEqual(s['modules']['M001']['phase'], 'dod')
        f.call('complete', {'dod_ref': f.ref('dod-final.md', 'Retained build and independent automation evidence'), 'checks_passed': True})
        self.assertEqual(f.state()['quality'], 'green-passed')

    def test_independent_auditor_can_verify_previously_unrun_module(self):
        f = self.run_final_audit()
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')
        f.call('complete', {'dod_ref': f.ref('audited-dod.md', 'Auditor verified every path'), 'checks_passed': True})
        self.assertEqual(f.state()['quality'], 'green-passed')

    def test_final_audit_red_reopens_deferred_module_for_repair(self):
        f = self.run_final_audit(actual=1)
        s = f.state()
        self.assertEqual(s['modules']['M001']['phase'], 'testing')
        self.assertEqual(s['modules']['M001']['quality'], 'red-bug')
        self.assertEqual(s['next_steps'][0]['operation'], 'repair-accept')
        self.assertFalse(s['modules']['M001']['blocked'])

    def test_audit_retest_environment_failure_finishes_batch_without_human_lock(self):
        f = self.f; self.prepare(); self.compile()
        cause = {'category': 'environment', 'summary': 'automation service absent', 'confidence': 'confirmed',
                 'owner': 'host', 'next_action': 'verify availability'}
        f.raw('audit-defer', {'root_cause': cause, 'evidence_ref': f.ref('env-issue.md', 'Service unavailable')})
        test_ledger.code_review(f)
        f.raw('audit-collect', {'batch_id': 'A1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        b = f.state()['audit_batch']; fid = next(iter(b['findings']))
        plan = {'routes': [{'finding_id': fid, 'source_module_id': 'M001', 'action': 'verify',
                'owner_module_ids': [], 'source_context': b['contexts']['M001'], 'owner_contexts': {},
                'root_cause': cause, 'analysis_ref': f.ref('analysis.md', 'Read SPEC and paths; verify service')}]}
        f.call('audit-plan', {'plan_ref': f.ref('audit-plan.json', plan)}, role='auditor', module=None)
        f.raw('audit-route-batch', {'review_ref': f.ref('route.md', 'Existing scope')}, role='global-orchestrator', module=None)
        f.raw('audit-retest')
        self.defer()
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-verdict')
        f.call('audit-verdict', {'review_ref': f.ref('audit-review.md', 'Not tested; retain Yellow')}, role='auditor', module=None)
        s = f.state()
        self.assertEqual(s['audit_batch']['status'], 'completed-with-unverified-tests')
        self.assertEqual(s['audit_batch']['resolved_findings'], [])
        self.assertEqual(s['audit_batch']['unverified_findings'], [fid])
        self.assertFalse(s['audit_queue'])
        self.assertEqual(s['global_next_step']['operation'], 'audit-assign')

    def test_build_discovery_prefers_user_then_wrapper_and_reports_ambiguity(self):
        f = self.f
        wrapper = f.target / 'gradlew'; wrapper.write_text('#!/bin/sh\nexit 99\n')
        found = discover(f.target)
        self.assertFalse(found['executed']); self.assertEqual(found['argv'][-1], 'assemble')
        selected = discover(f.target, {'argv': [sys.executable, '-c', 'pass']})
        self.assertEqual(selected['source'], 'user')
        wrapper.unlink()
        for name in ('one', 'two'):
            folder = f.target / name; folder.mkdir(); (folder / 'gradlew').write_text('exit 99')
        self.assertEqual(discover(f.target)['status'], 'needs-selection')
