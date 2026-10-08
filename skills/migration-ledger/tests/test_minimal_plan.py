"""A leaf that has its four-dimension specification plans with the minimal set: the Ledger fills what follows from the
accepted allocation, and what an author writes anyway is judged as before."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dimensions
import minimal_plan
from contracts import Rejected, check_ref, read_json
import test_dimensions
import test_source_changes

FOLLOWS = ('dimension_analysis_ref', 'source_closure', 'target_feasibility', 'decision_envelope', 'scenario_trace')


class MinimalPlanTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f

    def minimal(self, mid='M001', **keep):
        """The plan an author writes: the six-piece, the tasks with their scope and paths, the test plan and the trace."""
        f = self.f
        full = self.t.plan(mid)
        plan = copy.deepcopy(full)
        for key in FOLLOWS:
            plan.pop(key)
        for task in plan['tasks']:
            task.pop('dimension_analysis')
        plan.update(keep)
        if f.state().get('test_design_required'):
            from test_design_stage import prepare_design
            prepare_design(f, plan, mid)
        return full, plan

    def submit(self, plan, mid='M001', name='minimal-plan.json'):
        f = self.f
        ref = f.ref(name, plan)
        f.call('plan', {'plan_ref': ref}, role='spec-designer', module=mid)
        return ref, f.state()['modules'][mid]

    def test_the_ledger_fills_what_follows_from_the_accepted_allocation(self):
        full, plan = self.minimal()
        _, m = self.submit(plan)
        stored = m['plan']
        analysis, items = dimensions.load(m['dimension_analysis_ref'], 'M001')
        self.assertEqual(stored['dimension_analysis_ref'], m['dimension_analysis_ref'])
        closure = stored['source_closure']
        self.assertEqual(closure['verification'], m['behavior_review']['verification'])  # the review accepted with the allocation
        self.assertEqual(closure['execution_chain'], [item['source_locator'] for item in items.values()])
        self.assertTrue(closure['entry'] and closure['observable_result'] and closure['production_binding'] and closure['evidence_refs'])
        self.assertEqual(stored['target_feasibility'], {'verdict': 'ready', 'evidence_refs': analysis['source_reviews']['target']['evidence_refs']})
        envelope = stored['decision_envelope']
        self.assertEqual((envelope['scope'], envelope['allowed_alternatives']), (m['scope']['in'], []))
        self.assertEqual(envelope['acceptance'], [item['acceptance'] for item in items.values()])
        rows = stored['tasks'][0]['dimension_analysis']['dimensions']
        self.assertEqual([(row['dimension'], row['status'], row['item_ids']) for row in rows],
                         [('UI', 'not-applicable', []), ('Logic', 'applicable', ['M001-Logic']), ('Adhesive', 'not-applicable', []),
                          ('Resource', 'not-applicable', [])])
        self.assertIn('M001-Logic: new -> ', rows[1]['implementation'])
        self.assertEqual([(row['scenario_id'], row['task_ids']) for row in stored['scenario_trace']],
                         [(row['scenario_id'], row['task_ids']) for row in full['scenario_trace']])

    def test_the_minimal_plan_is_frozen_like_any_other(self):
        f = self.f
        _, plan = self.minimal()
        ref, m = self.submit(plan)
        self.assertEqual(m['phase'], 'clarifying')
        f.call('decision', {'decision_id': 'FREEZE', 'module_id': 'M001', 'decision': 'approved', 'subject_sha256': m['plan_hash'],
                            'human_source_ref': f.ref('freeze.md', 'Approve exact plan')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'FREEZE'}, module='M001')
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')

    def test_the_same_minimal_plan_submitted_again_is_the_plan_the_ledger_holds(self):
        _, plan = self.minimal()
        ref, m = self.submit(plan)
        self.f.call('plan', {'plan_ref': ref}, role='spec-designer', module='M001')
        again = self.f.state()['modules']['M001']
        self.assertEqual((again['plan_hash'], again['plan_submissions']), (m['plan_hash'], 1))  # completed the same way, not a new round

    def test_what_an_author_writes_anyway_is_kept_and_judged(self):
        proof = self.f.ref('feasibility.md', 'target review')
        _, pending = self.minimal(target_feasibility={'verdict': 'pending', 'evidence_refs': [proof]})
        with self.assertRaisesRegex(Rejected, 'target feasibility not ready'):
            self.submit(pending, name='pending-plan.json')
        _, partial = self.minimal(decision_envelope={'allowed_alternatives': ['draw the arrow as a shape']},
                                  source_closure={'entry': 'legacy/Settings#open'})
        _, m = self.submit(partial, name='partial-plan.json')
        self.assertEqual(m['plan']['decision_envelope']['allowed_alternatives'], ['draw the arrow as a shape'])
        self.assertEqual(m['plan']['decision_envelope']['scope'], m['scope']['in'])   # the rest still follows
        self.assertEqual(m['plan']['source_closure']['entry'], 'legacy/Settings#open')
        self.assertEqual(m['plan']['source_closure']['verification'], m['behavior_review']['verification'])


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        self.ref = d.f.ref('leaf-dimensions.json', d.analysis('M001', ('Logic', 'UI')))
        self.module = {'module_id': 'M001', 'dimension_analysis_ref': self.ref, 'scope': {'in': ['subfunction-M001']}}

    def plan(self, **over):
        return {'tasks': [{'task_id': 'T1'}, {'task_id': 'T2'}],
                'dimension_trace': [{'item_id': 'M001-Logic', 'task_ids': ['T1']}, {'item_id': 'M001-UI', 'task_ids': ['T1', 'T2']}], **over}

    def test_each_task_gets_its_own_share_of_the_four_dimensions(self):
        plan = minimal_plan.complete({}, self.module, self.plan())
        first, second = (task['dimension_analysis']['dimensions'] for task in plan['tasks'])
        self.assertEqual([(row['status'], row['item_ids']) for row in first],
                         [('applicable', ['M001-UI']), ('applicable', ['M001-Logic']), ('not-applicable', []), ('not-applicable', [])])
        self.assertEqual([(row['status'], row['item_ids']) for row in second][:2], [('applicable', ['M001-UI']), ('not-applicable', [])])
        self.assertEqual(second[1]['reason'], 'no item of this dimension is traced to this task')  # Logic applies to the leaf, not here
        self.assertEqual(second[2]['reason'], 'source-backed scope analysis')                      # the leaf's own reason for N/A
        self.assertNotIn('scenario_trace', plan)  # no scenario contract was asked for

    def test_an_authored_task_analysis_is_left_as_written(self):
        written = {'unresolved': [], 'dimensions': []}
        plan = self.plan(); plan['tasks'][0]['dimension_analysis'] = written
        plan = minimal_plan.complete({}, self.module, plan)
        self.assertIs(plan['tasks'][0]['dimension_analysis'], written)
        self.assertIn('dimension_analysis', plan['tasks'][1])

    def test_nothing_follows_without_the_leafs_own_specification(self):
        plan = self.plan()
        self.assertEqual(minimal_plan.complete({}, {'module_id': 'M001'}, copy.deepcopy(plan)), plan)
        other = self.plan(dimension_analysis_ref={'path': '/another/analysis.json', 'sha256': '0' * 64})
        self.assertEqual(minimal_plan.complete({}, self.module, copy.deepcopy(other)), other)


if __name__ == '__main__':
    unittest.main()
