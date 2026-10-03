"""Real Ledger design handoff; tests use isolated fixtures, never project code."""
import copy
import json
from pathlib import Path
import sys
import unittest

import test_ledger
import context_readiness as cr
import decomposition
import design_stage
import ledger
from contracts import Rejected, digest
from execute_test import execute


def start_design(f, plan, mid='M001', designer='designer'):
    s = f.state(); m = s['modules'][mid]
    for task in plan['tasks']:
        task.setdefault('scope', {'in': ['Implement allocated behavior'], 'out': [], 'write_paths': m['write_paths']})
    inp = {'schema_version': 1, 'module_id': mid, 'subject_sha256': design_stage.subject(s, m),
           'spec_refs': [r for r in plan['definitions'] if r['kind'] == 'spec'],
           'case_refs': [s['global_spec']], 'tasks': copy.deepcopy(plan['tasks'])}
    ref = f.ref(f'design-input-{mid}-{f.n}.json', inp)
    aid = f'DESIGN-{mid}-{f.n}'
    f.call('assign', {'assignment_id': aid, 'role': 'test-runner', 'mode': 'design',
                     'instance_id': designer, 'design_input_ref': ref}, module=mid)
    a = f.state()['modules'][mid]['assignments'][aid]
    result = {'schema_version': 1, 'kind': 'test-design', 'run_id': s['run_id'], 'module_id': mid,
              'assignment_id': aid, 'actor_instance_id': designer, 'freeze_id': None, 'code_baseline': None,
              'input_ref': ref, 'design_ref': f.ref(f'design-{mid}-{f.n}.md', 'Independent specification-derived coverage and expected behavior.'),
              'paths': copy.deepcopy(plan['paths'])}
    return a, result


def submit_design(f, a, result):
    ref = f.ref(f'design-result-{a["module_id"]}-{f.n}.json', result)
    p = {'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token'], 'result_ref': ref}
    s = f.state(); mid = a['module_id']
    if s.get('context_readiness_required'):
        reads = cr.input_refs(s, mid, 'test-design') + [ref]
        report = {'schema_version': 1, 'run_id': s['run_id'], 'module_id': mid, 'stage': 'test-design',
                  'producer': {'role': 'test-runner', 'instance_id': a['instance_id']},
                  'subject_sha256': cr.subject(s, mid, 'test-design'), 'verdict': 'ready',
                  'read_refs': reads, 'draft_ref': ref,
                  'checks': {k: {'status': 'ready', 'summary': 'Reviewed fixture scope, expected behavior and independent author.',
                                 'evidence_refs': [ref]} for k in cr.CHECKS['test-design']}}
        p['context_ref'] = f.ref(f'design-context-{mid}-{f.n}.json', report)  # the preflight rides the submit
    f.call('submit', p, role='test-runner', instance=a['instance_id'], module=mid)
    return ref


def prepare_design(f, plan, mid='M001'):
    a, result = start_design(f, plan, mid)
    ref = submit_design(f, a, result)
    f.call('accept', {'assignment_id': a['assignment_id'], 'review_ref': f.ref(f'design-review-{mid}-{f.n}.md',
            'MO reviewed each assigned CASE, requirements, PATHs and assertions.')}, module=mid)
    plan['test_design_ref'] = ref
    plan['definitions'] = [r if r['kind'] != 'test-design' else {**result['design_ref'], 'kind': 'test-design'} for r in plan['definitions']]
    return plan


class DesignStageTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.global_plan()

    def test_design_to_freeze_then_real_existing_execution_gate(self):
        f = self.f; plan = prepare_design(f, f.plan())
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'context'); self.assertEqual(m['results'], {})
        self.assertIsNone(m['code_baseline']); self.assertEqual(m['fix_rounds_used'], 0)
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'plan')
        f.call('plan', {'plan_ref': f.ref('accepted-plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D-design'); f.call('freeze', {'decision_id': 'D-design'})
        with self.assertRaises(Rejected): f.assign('test-runner', 'TOO-EARLY')
        f.implementation()
        a, result = f.make_test_result()
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')

    def test_plan_omits_the_design_binding_the_ledger_holds(self):
        f = self.f; plan = prepare_design(f, f.plan())
        ref = plan.pop('test_design_ref')
        with self.assertRaisesRegex(Rejected, 'plan must bind accepted test_design_ref'):
            f.call('plan', {'plan_ref': f.ref('wrong-binding.json', {**plan, 'test_design_ref': f.ref('other.json', {})})}, role='spec-designer')
        f.call('plan', {'plan_ref': f.ref('derived-binding.json', plan)}, role='spec-designer')
        self.assertEqual(f.state()['modules']['M001']['plan']['test_design_ref'], ref)
        f.approve(f.state()['next_steps'][0]['approval_subject_sha256'], 'D-derived'); f.call('freeze', {'decision_id': 'D-derived'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')

    def test_design_assignment_cannot_execute_or_submit_execution(self):
        f = self.f; a, result = start_design(f, f.plan())
        with self.assertRaisesRegex(Rejected, 'test assignment required'):
            execute(f.root, 'M001', a['assignment_id'], 'P1', [sys.executable, '-c', 'raise SystemExit(0)'], str(f.target), f.base/'out')
        result['kind'] = 'tests'
        with self.assertRaisesRegex(Rejected, 'only accepts test-design'):
            submit_design(f, a, result)
        self.assertFalse((f.base/'out').exists())

    def test_merged_fix_dispatch_cannot_reuse_design_author_or_consume_budget(self):
        f = self.f; plan = prepare_design(f, f.plan())
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'}); f.implementation()
        a, result = f.make_test_result(quality='red-bug')
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis.md', 'Code defect needs repair'),
                           'owner': 'fixer', 'root_cause': 'code'}, role='diagnostician')
        before = f.state()['modules']['M001']
        with self.assertRaisesRegex(Rejected, 'cannot implement or fix'):
            f.call('diagnosis-accept', {'assign': {'assignment_id': 'BAD-FIX', 'role': 'fixer', 'instance_id': 'designer'}})
        after = f.state()['modules']['M001']
        self.assertEqual(after, before)

    def test_mo_review_and_exact_accepted_content_required(self):
        f = self.f; plan = f.plan(); a, result = start_design(f, plan)
        ref = submit_design(f, a, result)
        with self.assertRaisesRegex(Rejected, 'absolute evidence'):
            f.call('accept', {'assignment_id': a['assignment_id']})
        with self.assertRaisesRegex(Rejected, 'worker still active'):
            f.call('plan', {'plan_ref': f.ref('early-plan.json', plan)}, role='spec-designer')
        f.call('accept', {'assignment_id': a['assignment_id'], 'review_ref': f.ref('review.md', 'MO reviewed')})
        plan['test_design_ref'] = ref
        plan['definitions'] = [r if r['kind'] != 'test-design' else {**result['design_ref'], 'kind': 'test-design'} for r in plan['definitions']]
        for label, mutate in (
            ('assertions', lambda p: p['paths'][0]['expected_assertions'][0].update(expected=999)),
            ('tasks', lambda p: p['tasks'][0]['scope']['in'].append('extra')),
            ('specs', lambda p: p['definitions'].append({**f.ref('extra-spec.md', 'extra'), 'kind': 'spec'})),
        ):
            bad = copy.deepcopy(plan); mutate(bad)
            with self.subTest(label=label), self.assertRaisesRegex(Rejected, 'differ'):
                f.call('plan', {'plan_ref': f.ref('bad-'+label+'.json', bad)}, role='spec-designer')
        with self.assertRaisesRegex(Rejected, 'Spec author must be independent'):
            f.call('plan', {'plan_ref': f.ref('own-plan.json', plan)}, role='spec-designer', instance=a['instance_id'])

    def test_missing_cases_observed_assertions_and_wrong_identity_rejected(self):
        f = self.f; a, good = start_design(f, f.plan())
        for change, message in (
            (lambda r: r['paths'][0].update(case_id='outside'), 'assigned cases'),
            (lambda r: r['paths'][0].update(quality='green-passed'), 'claim execution'),
            (lambda r: r['paths'][0]['expected_assertions'][0].update(actual=2, passed=True), 'expectation only'),
            (lambda r: r.update(actor_instance_id='other'), 'actor mismatch'),
        ):
            bad = copy.deepcopy(good); change(bad)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message): submit_design(f, a, bad)
        with self.assertRaisesRegex(Rejected, 'worker identity'):
            f.call('submit', {'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token']}, role='test-runner', instance='other')
        with self.assertRaisesRegex(Rejected, 'fencing token'):
            f.call('submit', {'assignment_id': a['assignment_id'], 'fencing_token': -1}, role='test-runner', instance=a['instance_id'])

    def test_revoke_returns_to_planning_and_old_submission_cannot_be_accepted(self):
        f = self.f; a, result = start_design(f, f.plan()); submit_design(f, a, result)
        f.call('revoke', {'assignment_id': a['assignment_id'], 'stopped_worker_ref': f.ref('stopped.md', 'Host stopped actual fixture worker')}, role='host')
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'context'); self.assertTrue(m['test_design_required'])
        self.assertEqual(f.state()['next_steps'][0]['mode'], 'design')
        with self.assertRaisesRegex(Rejected, 'inactive'): submit_design(f, a, result)
        with self.assertRaisesRegex(Rejected, 'no active submission'): f.call('accept', {'assignment_id': a['assignment_id']})

    def test_plan_takes_paths_task_scope_and_spec_from_the_accepted_design(self):
        f = self.f; full = prepare_design(f, f.plan())
        lean = copy.deepcopy(full)
        del lean['paths']
        lean['definitions'] = [d for d in lean['definitions'] if d['kind'] not in ('spec', 'test-design')]
        for task in lean['tasks']:
            for key in ('scope', 'requirement_ids', 'global_requirement_ids'):
                task.pop(key, None)
        changed = copy.deepcopy(lean); changed['paths'] = copy.deepcopy(full['paths'])
        changed['paths'][0]['expected_assertions'][0]['expected'] = 'something else'
        with self.assertRaisesRegex(Rejected, 'differ from accepted design'):  # what a plan still carries must match
            f.call('plan', {'plan_ref': f.ref('changed-plan.json', changed)}, role='spec-designer')
        f.call('plan', {'plan_ref': f.ref('lean-plan.json', lean)}, role='spec-designer')
        m = f.state()['modules']['M001']
        self.assertEqual(m['plan']['paths'], full['paths'])
        self.assertEqual(m['plan']['tasks'], full['tasks'])
        key = lambda d: (d['kind'], d['sha256'])
        self.assertEqual(sorted(m['plan']['definitions'], key=key), sorted(full['definitions'], key=key))
        self.assertNotEqual(m['plan_hash'], digest(lean))  # the Ledger hashes the plan it completed
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['ready'], step['approval_subject_sha256']), ('freeze', False, m['plan_hash']))
        f.approve(step['approval_subject_sha256'], 'D-lean'); f.call('freeze', {'decision_id': 'D-lean'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')

    def test_invalidation_preserves_history_and_requires_new_design(self):
        f = self.f; plan = prepare_design(f, f.plan())
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})
        with self.assertRaisesRegex(Rejected, 'cannot implement'):
            f.call('assign', {'role': 'implementer', 'assignment_id': 'bad', 'instance_id': 'designer'})
        f.call('invalidate', {'reason': 'task boundary revised'})
        m = f.state()['modules']['M001']
        self.assertIn('accepted_test_design', m['planning_history'][-1])
        with self.assertRaisesRegex(Rejected, 'accepted independent'):
            f.call('plan', {'plan_ref': f.ref('old-plan.json', plan)}, role='spec-designer')
        self.assertEqual(f.state()['next_steps'][0]['mode'], 'design')

    def test_design_input_cites_the_cursor_subject_instead_of_copying_the_context(self):
        f = self.f
        s = f.state(); s['test_design_required'] = True; m = s['modules']['M001']
        step = ledger.next_step(s, m)
        self.assertEqual((step['operation'], step['mode']), ('assign', 'design'))
        self.assertEqual(step['input_subject_sha256'], design_stage.subject(s, m))
        plan = f.plan()
        for task in plan['tasks']:
            task['scope'] = {'in': ['fixture'], 'out': [], 'write_paths': m['write_paths']}
        inp = {'schema_version': 1, 'module_id': 'M001', 'tasks': plan['tasks'],
               'spec_refs': [r for r in plan['definitions'] if r['kind'] == 'spec'], 'case_refs': [s['global_spec']]}
        for subject in (None, '0' * 64):
            doc = {**inp, 'subject_sha256': subject} if subject else inp
            with self.subTest(subject=subject), self.assertRaisesRegex(Rejected, 'allocation/context stale'):
                f.call('assign', {'assignment_id': 'BAD-' + str(f.n), 'role': 'test-runner', 'mode': 'design', 'instance_id': 'designer',
                                 'design_input_ref': f.ref(f'input-{f.n}.json', doc)})
        f.call('assign', {'assignment_id': 'DESIGN', 'role': 'test-runner', 'mode': 'design', 'instance_id': 'designer',
                         'design_input_ref': f.ref('input.json', {**inp, 'subject_sha256': step['input_subject_sha256']})})
        self.assertEqual(f.state()['modules']['M001']['assignments']['DESIGN']['input_subject'], step['input_subject_sha256'])

    def test_tampered_input_is_visible_and_does_not_crash_status(self):
        f = self.f; a, result = start_design(f, f.plan())
        Path(a['design_input_ref']['path']).write_text('{}')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): submit_design(f, a, result)
        self.assertEqual(f.state()['modules']['M001']['phase'], 'context')
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['role'], step['reason']), ('revoke', 'host', 'design-input-stale'))

    def test_stale_accepted_design_returns_to_replanning_without_losing_history(self):
        f = self.f; plan = prepare_design(f, f.plan())
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        Path(plan['test_design_ref']['path']).write_text('{}')
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['reason']), ('invalidate', 'independent-test-design-stale'))
        f.call('invalidate', step['payload'])
        m = f.state()['modules']['M001']
        self.assertIsNone(m.get('design_input_ref'))
        self.assertIn('design_input_ref', m['planning_history'][-1])
        self.assertEqual(f.state()['next_steps'][0]['mode'], 'design')

    def test_design_worker_must_supply_own_current_context_receipt(self):
        import test_context_readiness
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups); f.global_plan()
        # A real Spec draft may precede design, but its author is not the designer.
        draft = f.ref('spec-draft.json', f.plan())
        f.record(f.report('planning', instance='spec-instance', draft=draft))
        s = f.state(); plan = f.plan()
        for task in plan['tasks']:
            task['scope'] = {'in': ['fixture'], 'out': [], 'write_paths': s['modules']['M001']['write_paths']}
        inp = {'schema_version': 1, 'module_id': 'M001', 'subject_sha256': design_stage.subject(s, s['modules']['M001']), 'tasks': plan['tasks'],
               'spec_refs': [r for r in plan['definitions'] if r['kind'] == 'spec'], 'case_refs': [s['global_spec']]}
        with self.assertRaisesRegex(Rejected, 'independent'):
            f.call('assign', {'assignment_id': 'OWN-DESIGN', 'role': 'test-runner', 'mode': 'design',
                             'instance_id': 'spec-instance', 'design_input_ref': f.ref('input.json', inp)})
        a, result = start_design(f, plan)
        ref = f.ref('result.json', result)
        with self.assertRaisesRegex(Rejected, 'context readiness receipt required'):
            f.raw('submit', {'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token'], 'result_ref': ref},
                  role='test-runner', instance=a['instance_id'])
        events = len(ledger.read_events(f.root)[1])
        submit_design(f, a, result)
        self.assertEqual(len(ledger.read_events(f.root)[1]), events + 1)  # report and result in one event
        self.assertIn('test-design:' + a['instance_id'], f.state()['modules']['M001']['context_receipts'])

    def test_independent_sibling_and_unfinished_dependency_can_design(self):
        f = self.f
        f.call('register', {'module_id': 'M002', 'case_ids': ['C1'], 'write_paths': [str(f.target/'m2')], 'dependencies': ['M001']}, role='global-orchestrator', module=None)
        f.global_plan(); before = copy.deepcopy(f.state()['modules']['M001'])
        plan = f.plan(); plan['module_id'] = 'M002'
        prepare_design(f, plan, 'M002')
        self.assertEqual(f.state()['modules']['M001'], before)
        self.assertEqual(f.state()['modules']['M002']['results'], {})

    def test_context_receipt_binds_real_design_assignment_and_result(self):
        import test_context_readiness
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups); f.global_plan()
        plan = prepare_design(f, f.plan())
        f.call('plan', {'plan_ref': f.ref('ready-plan.json', plan)}, role='spec-designer')
        f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')

    def test_prepared_gate_cannot_be_disabled(self):
        import test_project_context
        f = test_project_context.ProjectContextTests(); f.setUp(); self.addCleanup(f.doCleanups)
        prepared = f.prepare(); self.assertIs(prepared['input']['test_design_required'], True)
        payload = f.init_payload(prepared); payload['test_design_required'] = False
        with self.assertRaisesRegex(Rejected, 'test design gate mismatch'): f.start(payload)


if __name__ == '__main__':
    unittest.main()
