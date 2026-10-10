"""What the unified audit finds wrong in a SPEC or in how the scope was cut is traced back to the slices and parents that
revise it, bottom-up and without a human release; what was built is kept and brought to the revised SPEC."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
import test_audit_closure
import test_decomposition
from contracts import Rejected


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.c = c = test_audit_closure.ClosureTests(); c.setUp(); self.addCleanup(c.doCleanups)
        c.cross_module_failure()
        test_ledger.code_review(c)
        c.call('audit-collect', {'batch_id': 'B1', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)

    def route(self, action='trace', owners=('M001',), **extra):
        return {'source_module_id': 'M002', 'owner_module_ids': list(owners), 'action': action,
                'root_cause': {'category': 'planning-gap', 'summary': 'the provider SPEC never stated the shared value', 'confidence': 'confirmed',
                               'owner': 'M001', 'next_action': 'revise-spec'},
                'analysis_ref': self.c.ref('trace-analysis.md', 'SPEC, tasks and the split reviewed bottom-up'), **extra}

    def plan(self, *routes):
        c = self.c
        c.call('audit-plan', {'plan_ref': c.ref('routes-%d.json' % c.n, {'routes': list(routes)})}, role='auditor', module=None)
        c.call('audit-route-batch', {'review_ref': c.ref('route-review.md', 'Global confirmed who revises')}, role='global-orchestrator', module=None)

    def test_a_finding_traced_back_is_recorded_for_its_slice_and_the_batch_is_released_without_a_human(self):
        c = self.c
        self.plan(self.route())
        state = c.state()
        self.assertEqual((state['audit_batch']['status'], state['audit_batch']['released_for']), ('released', 'traceback'))
        issue_id, issue = next(iter(state['issues'].items()))
        self.assertRegex(issue_id, '^TRACE-B1-F-M002-')
        self.assertEqual((issue['kind'], issue['applies_to'], issue['blocks'], issue['summary']),
                         ('defect', ['M001'], False, 'the provider SPEC never stated the shared value'))
        step = next(x for x in state['next_steps'] if x['module_id'] == 'M001')
        self.assertEqual((step['reason'], step['issue_ids'], step['recovery_action']), ('open-issues', [issue_id], 'change-or-realloc-request'))
        with self.assertRaisesRegex(Rejected, 'open-issues'):  # the audit collects again once what it sent back is revised
            c.call('audit-collect', {'batch_id': 'B2', 'auditor_instance_id': 'auditor'}, role='global-orchestrator', module=None)
        baseline = state['modules']['M001']['code_baseline']
        c.call('change', {'request_ref': c.ref('cr.md', 'state the shared value in the SPEC'), 'impact_ref': c.ref('impact.md', 'one task, its path')}, module='M001')
        module = c.state()['modules']['M001']
        self.assertEqual((module['phase'], module['code_baseline']), ('change-review', baseline))  # its SPEC is reopened, its code stays

    def test_a_finding_that_needs_a_human_keeps_the_batch_for_the_human(self):
        import audit_closure
        mixed = {'batch_id': 'B9', 'status': 'repairing', 'routes': {'F1': {**self.route(), 'finding_id': 'F1'},
                                                                      'F2': {**self.route('human', owners=()), 'finding_id': 'F2'}}}
        state = {'audit_batch': mixed, 'modules': {}}
        audit_closure.trace_back(state, mixed, {'role': 'global-orchestrator', 'instance_id': 'go'})
        self.assertEqual((mixed['status'], list(state['issues'])), ('repairing', ['TRACE-B9-F1']))  # recorded, and the human decides the rest first
        c = self.c
        self.plan(self.route('human', owners=()))
        self.assertNotEqual(c.state()['audit_batch']['status'], 'released')
        self.assertNotIn('issues', c.state())

    def test_who_revises_is_named(self):
        for route, message in ((self.route(owners=()), 'only fix and trace routes specify owners'),
                               (self.route(owners=('M999',)), 'unknown/duplicate repair owner'),
                               (self.route('verify', owners=('M001',)), 'only fix and trace routes specify owners')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.c.call('audit-plan', {'plan_ref': self.c.ref('bad-routes.json', {'routes': [route]})}, role='auditor', module=None)


class ParentTests(unittest.TestCase):
    def test_an_issue_recorded_for_a_parent_offers_it_a_re_split(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split(); f.global_plan()
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M010')
        self.assertIsNone(step['operation'])
        f.call('issue', {'issue_id': 'CUT', 'kind': 'defect', 'summary': 'two slices write the same screen', 'applies_to': ['M010']},
               role='auditor', module=None)
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M010')
        self.assertEqual((step['operation'], step['ready'], step['reason'], step['issue_ids']), ('redecompose', True, 'open-issues', ['CUT']))
        f.call('issue-resolve', {'issue_id': 'CUT', 'module_id': 'M010', 'evidence_ref': f.ref('split-review.md', 'the split stands: one writer per file')},
               role='module-orchestrator', module=None)
        step = next(x for x in f.state()['next_steps'] if x['module_id'] == 'M010')
        self.assertIsNone(step['operation'])


class KeptCodeTests(unittest.TestCase):
    def test_code_written_under_a_plan_that_is_given_up_is_carried_to_the_next_one(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        written = f.state()['modules']['M001']['code_files']
        f.call('invalidate', {'reason': 'the split behind this plan was revised'})
        module = f.state()['modules']['M001']
        self.assertEqual((module['phase'], module['code_files'], module['code_baseline'], module['carried_files']), ('specifying', [], None, written))
        self.assertEqual(ledger.status(f.root, 'step', 'M001')['module']['carried_files'], written)  # its planner sees what exists
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('next-plan.json', plan)}, role='spec-designer')
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D2'); f.call('freeze', {'decision_id': 'D2'})
        step = f.state()['next_steps'][0]
        self.assertEqual((step['worker_role'], step['carried_files']), ('implementer', [ref['path'] for ref in written]))  # adjust them, do not start over
        f.implementation(aid='I2')
        self.assertNotIn('carried_files', f.state()['modules']['M001'])  # written again under the new plan: nothing is left over

    def test_a_leaf_that_waited_for_its_provider_goes_on_where_it_was(self):
        revising = {'phase': 'change-review', 'freeze_id': 'F1', 'change_request': {'request_ref': {}}}
        self.assertEqual(ledger.resume_after_provider(revising), 'change-review')  # in the revision of its own SPEC
        self.assertEqual(ledger.resume_after_provider({**revising, 'phase': 'clarifying'}), 'clarifying')
        self.assertEqual(ledger.resume_after_provider({'phase': 'testing', 'freeze_id': 'F1'}), 'frozen')
        self.assertEqual(ledger.resume_after_provider({'phase': 'specifying', 'freeze_id': None}), 'specifying')
        self.assertEqual(ledger.resume_after_provider({'phase': 'waiting-human', 'freeze_id': None, 'blocked': {'resume_phase': 'clarifying'}}), 'clarifying')
        module = {**copy.deepcopy(revising), 'revision': 3}
        ledger.await_provider(module)
        self.assertEqual((module['phase'], module['blocked']['resume_phase']), ('waiting-dependency', 'change-review'))


class LessonTests(unittest.TestCase):
    def test_what_an_audit_sent_back_is_a_lesson_about_the_split(self):
        from openspec_projection import build_lessons
        issue = {'kind': 'defect', 'summary': 'two slices write the same screen', 'applies_to': ['M010', 'M001'], 'blocks': False,
                 'evidence_refs': [], 'raised_by': {'role': 'global-orchestrator'}, 'resolved': {'M001': {}},
                 'traced_from': {'batch_id': 'B1', 'finding_id': 'F1', 'source_module_id': 'M002'}}
        state = {'run_id': 'demo', 'modules': {}, 'issues': {'TRACE-B1-F1': issue, 'NOTE': {**issue, 'traced_from': None}}}
        entry, = [row for row in build_lessons(state, 7)['entries'] if row['kind'] == 'boundary-conflict']
        self.assertEqual((entry['status'], entry['module_id'], entry['affected_modules'], entry['summary']),
                         ('pending', 'M002', ['M010', 'M001'], 'two slices write the same screen'))
        issue['resolved']['M010'] = {}
        self.assertEqual([row['status'] for row in build_lessons(state, 8)['entries'] if row['kind'] == 'boundary-conflict'], ['resolved'])

    def test_a_revised_split_is_harvested_when_it_happens(self):
        self.assertEqual(ledger.RESLICED, ('redecompose-accept', 'revise-run', 'audit-route-batch'))
        calls = []
        import experience
        original = experience.auto_harvest
        experience.auto_harvest = lambda root, force=False: calls.append(force) or {'entries': 0}
        self.addCleanup(setattr, experience, 'auto_harvest', original)
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split(); f.global_plan()
        self.assertEqual(calls, [])  # a first split is not a lesson yet
        f.call('realloc-request', {'reason': 'the slice needs another write path', 'evidence_refs': [f.ref('need.md', 'read the source')]}, module='M001')
        f.call('redecompose', {'plan_ref': f.ref('resplit.json', f.proposal())}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('resplit-review.md', 'reviewed')}, role='global-orchestrator', module='M010')
        self.assertEqual(calls, [True])  # harvested at once, whether or not the run ever settles


if __name__ == '__main__':
    unittest.main()
