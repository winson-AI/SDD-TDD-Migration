"""An upstream revision that keeps a frozen leaf's boundary reaches the leaf as a change to its contract."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import test_feedback_repair
import test_run_changes
import test_validation as tv
from contracts import Rejected


class ResplitTests(unittest.TestCase):
    """A parent with two leaves; M001 is completed (planned, frozen, coded, verified Green), M002 is coded."""
    def setUp(self):
        self.t = test_run_changes.RootRevisionTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def build(self):
        f = self.f
        f.prepare_leaf('M001'); f.complete_leaf('M001'); f.prepare_leaf('M002')

    def resplit(self, change):
        f = self.f
        proposal = f.proposal(); change(proposal)
        f.call('redecompose', {'plan_ref': f.ref('revision-%d.json' % f.n, proposal)}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('revision-review-%d.md' % f.n, 'reviewed')},
               role='global-orchestrator', module='M010')
        return f.state()

    @staticmethod
    def supplement(f):
        def change(proposal):
            child = proposal['children'][0]
            child['context_refs'] = child['context_refs'] + [f.ref('supplement.md', 'more evidence for the same boundary')]
        return change

    def test_a_revision_that_keeps_the_boundary_reopens_the_contract_and_keeps_the_code(self):
        self.build(); f = self.f
        before = f.state()['modules']['M001']
        state = self.resplit(self.supplement(f))
        m = state['modules']['M001']
        self.assertEqual(m['phase'], 'change-review')
        for key in ('freeze_id', 'plan_hash', 'code_files', 'code_baseline', 'accepted_task_ids', 'results'):
            self.assertEqual(m[key], before[key], key)  # nothing that was built is thrown away
        self.assertEqual(m.get('planning_history', []), [])
        request = m['change_request']
        self.assertTrue(request['upstream'])
        self.assertEqual((request['from_freeze_id'], request['previous_plan']['plan_hash']), (before['freeze_id'], before['plan_hash']))
        self.assertEqual(len(m['context_refs']), len(before['context_refs']) + 1)  # the leaf now holds the revised allocation
        self.assertEqual(state['redecomposition_history'][-1]['revised_modules'], ['M001'])
        step = next(row for row in state['next_steps'] if row['module_id'] == 'M001')
        self.assertEqual((step['operation'], step['role'], step['ready']), ('plan', 'spec-designer', True))

    def test_a_revision_that_only_renews_evidence_does_not_stop_the_sibling(self):
        self.build(); f = self.f
        before = f.state()
        state = self.resplit(self.supplement(f))
        self.assertEqual(state['global_plan'], before['global_plan'])  # the accepted coverage did not move
        sibling = state['modules']['M002']
        self.assertEqual((sibling['phase'], sibling['freeze_id']), (before['modules']['M002']['phase'], before['modules']['M002']['freeze_id']))
        step = next(row for row in state['next_steps'] if row['module_id'] == 'M002')
        self.assertTrue(step['ready'], step)

    def test_a_revision_that_takes_from_the_boundary_plans_the_leaf_again(self):
        self.build(); f = self.f
        for change in (lambda p: p['children'][0]['scope'].update(out=['Orders', 'history']),          # an exclusion is added
                       lambda p: p['children'][0]['scope'].update({'in': ['a reworded scope statement']})):
            with self.subTest():
                self.setUp(); self.build(); f = self.f
                state = self.resplit(change)
                m = state['modules']['M001']
                self.assertEqual((m['phase'], m['plan'], m['freeze_id']), ('specifying', None, None))
                self.assertEqual(len(m['planning_history']), 1)
                self.assertIsNone(state['global_plan'])  # the accepted coverage moved: GO reviews it again
                self.assertEqual(state['redecomposition_history'][-1]['revised_modules'], [])

    def test_a_leaf_that_is_not_frozen_plans_again(self):
        f = self.f
        plan = f.plan(); plan['module_id'] = 'M001'; f.attach_reuse(plan)
        f.call('plan', {'plan_ref': f.ref('draft-plan.json', plan)}, role='spec-designer', module='M001')
        state = self.resplit(self.supplement(f))
        m = state['modules']['M001']
        self.assertEqual((m['phase'], m['plan']), ('specifying', None))
        self.assertNotIn('change_request', m)

    def test_boundary_kept_means_nothing_is_taken_away(self):
        f = self.f
        old = f.state()['modules']['M001']
        kept = lambda **change: decomposition.boundary_kept(old, {**copy.deepcopy(old), **change}, old['dependencies'])
        self.assertTrue(kept())
        self.assertTrue(kept(case_ids=old['case_ids'] + ['C9'], write_paths=[str(f.target)]))  # more cases, a wider write scope
        self.assertTrue(kept(scope={**old['scope'], 'in': old['scope']['in'] + ['one more statement'], 'out': []}))
        self.assertFalse(kept(case_ids=[]))
        self.assertFalse(kept(write_paths=[str(f.target / 'elsewhere')]))
        self.assertFalse(kept(scope={**old['scope'], 'requirement_ids': []}))
        self.assertFalse(kept(acceptance_case_ids=[]))
        self.assertFalse(decomposition.boundary_kept(old, old, ['M002']))  # another dependency is another boundary


class DependentTests(unittest.TestCase):
    def test_a_leaf_that_only_depends_on_a_revised_leaf_keeps_its_plan_and_waits(self):
        t = test_run_changes.RootRevisionTests()
        t.f = f = test_run_changes.test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); f.split(f.proposal(dependencies={'M002': ['M001']})); f.global_plan()
        plan = f.plan(); plan['module_id'] = 'M002'; plan['paths'][0]['path_id'] = 'P2'; plan['tasks'][0]['path_ids'] = ['P2']
        f.attach_reuse(plan)
        f.call('plan', {'plan_ref': f.ref('plan-M002.json', plan)}, role='spec-designer', module='M002')
        f.call('decision', {'decision_id': 'M002', 'decision': 'approved', 'module_id': 'M002', 'subject_sha256': f.state()['modules']['M002']['plan_hash'],
                            'human_source_ref': f.ref('decision-M002.md', 'approved')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'M002'}, module='M002')  # the consumer is frozen and waits for its provider
        f.prepare_leaf('M001'); f.complete_leaf('M001')
        before = f.state()['modules']['M002']
        self.assertEqual(before['phase'], 'waiting-dependency')
        proposal = f.proposal(dependencies={'M002': ['M001']})
        proposal['children'][0]['context_refs'] = proposal['children'][0]['context_refs'] + [f.ref('supplement.md', 'more evidence')]
        f.call('redecompose', {'plan_ref': f.ref('revision.json', proposal)}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('revision-review.md', 'reviewed')}, role='global-orchestrator', module='M010')
        state = f.state(); consumer = state['modules']['M002']
        self.assertEqual(state['modules']['M001']['phase'], 'change-review')
        self.assertEqual((consumer['phase'], consumer['blocked']['reason']), ('waiting-dependency', 'dependency-version-changed'))
        for key in ('plan_hash', 'freeze_id'):
            self.assertEqual(consumer[key], before[key], key)
        self.assertEqual(consumer.get('planning_history', []), [])


class UnchangedContractTests(unittest.TestCase):
    """A leaf with two coded tasks whose paths are all Green; its contract is reopened and no TASK changes."""
    def setUp(self):
        self.r = r = test_feedback_repair.TaskIndependenceTests(); r.setUp(); self.addCleanup(r.doCleanups)
        self.f = f = r.f
        r.t.freeze(r.plan()); r.implement(['T1'], 'I1'); r.implement(['T2'], 'I2')
        r.execute_paths('BUILD1', 'build', ['B']); r.execute_paths('TEST1', 'automation', ['P1', 'P2'])

    def refreeze(self, affected, unchanged):
        f = self.f; old = f.state()['modules']['M001']
        plan = copy.deepcopy(old['plan'])
        plan['source_closure']['observable_result'] = plan['source_closure']['observable_result'] + ' (evidence renewed)'
        f.call('change', {'request_ref': f.ref('cr.md', 'the allocation gained evidence'), 'impact_ref': f.ref('impact.md', 'no task moves')})
        f.call('plan', {'plan_ref': f.ref('same-tasks-plan.json', plan)}, role='spec-designer')
        proof = {'schema_version': 1, 'from_freeze_id': old['freeze_id'], 'to_plan_hash': f.state()['modules']['M001']['plan_hash'],
                 'reviewer_instance_id': 'module-orchestrator', 'affected_task_ids': affected, 'unchanged_task_ids': unchanged,
                 'tasks': [{'task_id': tid, 'depends_on': [], 'input_refs': [],
                            'evidence_refs': [f.ref('isolation-' + tid + '.md', 'independent inputs reviewed')]} for tid in ('T1', 'T2')]}
        f.call('plan-review', {'review_ref': self.r.t.review(task_independence_ref=f.ref('independence.json', proof))})
        f.call('freeze', f.state()['next_steps'][0]['payload'])
        return old

    def test_no_task_changes_so_the_code_stands_and_the_leaf_only_rebuilds(self):
        old = self.refreeze([], ['T1', 'T2']); f = self.f
        m = f.state()['modules']['M001']
        self.assertEqual((m['phase'], m['accepted_task_ids'], m['task_revalidation']['mode']), ('testing', ['T1', 'T2'], 'partial'))
        self.assertEqual((m['code_baseline'], m['execution_partition_pending']), (old['code_baseline'], False))
        self.assertTrue(m['results']['B']['stale'])  # the build is always run again
        self.assertTrue(tv.path_green(m, 'P1') and tv.path_green(m, 'P2'))  # the Green paths of unchanged tasks stand
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['worker_role'], step['test_scope']), ('assign', 'test-runner', 'build'))
        self.r.execute_paths('BUILD2', 'build', ['B'])
        m = f.state()['modules']['M001']
        self.assertEqual(m['phase'], 'dod'); self.assertTrue(tv.all_green(m))

    def test_a_changed_task_must_still_be_declared(self):
        f = self.f; old = f.state()['modules']['M001']
        plan = copy.deepcopy(old['plan']); plan['tasks'][0]['name'] = 'T1 does something else now'
        f.call('change', {'request_ref': f.ref('cr.md', 'T1 moves'), 'impact_ref': f.ref('impact.md', 'T1')})
        f.call('plan', {'plan_ref': f.ref('moved-plan.json', plan)}, role='spec-designer')
        proof = {'schema_version': 1, 'from_freeze_id': old['freeze_id'], 'to_plan_hash': f.state()['modules']['M001']['plan_hash'],
                 'reviewer_instance_id': 'module-orchestrator', 'affected_task_ids': [], 'unchanged_task_ids': ['T1', 'T2'],
                 'tasks': [{'task_id': tid, 'depends_on': [], 'input_refs': [],
                            'evidence_refs': [f.ref('isolation-' + tid + '.md', 'reviewed')]} for tid in ('T1', 'T2')]}
        with self.assertRaisesRegex(Rejected, 'omits changed TASK'):
            f.call('plan-review', {'review_ref': self.r.t.review(task_independence_ref=f.ref('independence.json', proof))})


class RunRevisionTests(unittest.TestCase):
    def setUp(self):
        self.t = test_run_changes.PreparedRunRevisionTests(); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def report(self, action):
        report = self.t.report({'build': {'timeout_seconds': 20}}, affected=('M001',))
        next(row for row in report['modules'] if row['module_id'] == 'M001')['action'] = action
        return report

    def test_a_run_revision_can_reach_a_frozen_leaf_as_a_contract_change(self):
        f = self.f
        self.t.source.freeze('M001')
        before = f.state()['modules']['M001']
        self.assertTrue(before['freeze_id'])
        payload = self.t.review(self.report('revise'))
        f.call('revise-run', payload, role='host', module=None)
        m = f.state()['modules']['M001']
        self.assertEqual((m['phase'], m['freeze_id'], m['plan_hash']), ('change-review', before['freeze_id'], before['plan_hash']))
        self.assertEqual(m.get('code_files'), before.get('code_files'))
        self.assertTrue(m['change_request']['upstream'])

    def test_a_leaf_that_is_not_frozen_cannot_take_a_revision_as_a_contract_change(self):
        f = self.f
        self.assertIsNone(f.state()['modules']['M001']['freeze_id'])
        report = self.report('revise')
        ref = f.ref('unfrozen-revise.json', report)
        receipt = f.ref('unfrozen-context.json', f.report('global-planning', module=None, draft=ref))
        with self.assertRaisesRegex(Rejected, 'revise needs a frozen'):
            f.raw('run-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)


if __name__ == '__main__':
    unittest.main()
