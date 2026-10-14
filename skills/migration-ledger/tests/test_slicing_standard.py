"""The slicing standard: a leaf is one UI surface with the Logic, Adhesive and Resource items behind it; the shell the
leaves plug into is a scaffold; features depend on scaffolds only; a leaf holds at most twenty cases and plans at most
eight tasks; and the audit reads back, per leaf, the signals that say a split was too fine."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import ledger
import reading
import test_decomposition
import test_dimensions
from contracts import Rejected, check_ref, file_ref


class DependencyShapeTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project')

    def test_a_feature_leaf_depends_on_scaffold_leaves_only(self):
        f = self.f
        plan = f.proposal(dependencies={'M002': ['M001']})
        plan['children'][0].pop('kind')  # M001 is what M002 builds on, but is declared a feature
        with self.assertRaisesRegex(Rejected, 'depends only on scaffold leaves'):
            f.call('decompose', {'plan_ref': f.ref('features.json', plan)}, module='M010')
        plan['children'][0]['kind'] = 'scaffold'
        f.call('decompose', {'plan_ref': f.ref('scaffolded.json', plan)}, module='M010')
        f.call('decompose-accept', {'review_ref': f.ref('review.md', 'reviewed')}, role='global-orchestrator', module='M010')
        self.assertEqual((f.state()['modules']['M001']['kind'], f.state()['modules']['M002']['kind']), ('scaffold', 'scaffold'))  # the kind is registered; M002 accepts no case, so it is a scaffold too

    def test_an_unknown_kind_and_a_leaf_over_twenty_cases_are_refused(self):
        f = self.f
        plan = f.proposal(); plan['children'][0]['kind'] = 'layer'
        with self.assertRaisesRegex(Rejected, 'unknown child kind'):
            f.call('decompose', {'plan_ref': f.ref('kind.json', plan)}, module='M010')
        plan = f.proposal(); plan['children'][0]['case_ids'] = ['C%d' % i for i in range(21)]
        with self.assertRaisesRegex(Rejected, 'at most 20 cases|outside selected function'):  # too many cases for one surface
            f.call('decompose', {'plan_ref': f.ref('coarse.json', plan)}, module='M010')


class AnchoredLeafTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        self.f = d.f

    def split(self, accepting, supporting, anchor=None):
        """A UI+Logic parent split into the leaf that accepts its case and a supporting slice, each with its own dimensions."""
        d, f = self.d, self.f
        plan = d.proposal(kinds=('UI', 'Logic'), ids=('M001', 'M002'))
        for child, kinds in zip(plan['children'], (accepting, supporting)):
            child['dimension_analysis_ref'] = f.ref(child['module_id'] + '-own.json', d.analysis(child['module_id'], kinds, d.root_ref))
            child.pop('anchor_ui', None)
        if anchor:
            plan['children'][0]['anchor_ui'] = anchor
        return plan

    def test_under_a_parent_with_ui_the_accepting_leaf_anchors_on_a_ui_surface_and_is_not_a_single_layer(self):
        d, f = self.d, self.f
        d.root(kinds=('UI', 'Logic'))
        with self.assertRaisesRegex(Rejected, 'anchors on a UI surface'):
            f.call('decompose', {'plan_ref': f.ref('layer.json', self.split(('Logic',), ('UI',)))}, module='M010')  # the screen went to the supporting slice
        with self.assertRaisesRegex(Rejected, 'not a single layer'):
            f.call('decompose', {'plan_ref': f.ref('screen.json', self.split(('UI',), ('Logic',), anchor='Login page'))}, module='M010')
        f.call('decompose', {'plan_ref': f.ref('anchored.json', self.split(('UI', 'Logic'), ('Logic',), anchor='Login page'))}, module='M010')  # the surface with the logic behind it; the supporting slice may be one layer

    def test_a_parent_without_ui_does_not_ask_its_leaves_for_one(self):
        d, f = self.d, self.f
        d.root(kinds=('Logic',))
        f.call('decompose', {'plan_ref': f.ref('parser.json', d.proposal(kinds=('Logic',)))}, module='M010')  # a pure parser has no screen to anchor


class PlanBoundsTests(unittest.TestCase):
    def test_more_than_eight_tasks_and_a_plan_over_sixty_kilobytes_are_owed(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); f.split(f.proposal()); f.global_plan()
        plan = f.plan(); plan['module_id'] = 'M001'; f.attach_reuse(plan)
        first = plan['tasks'][0]
        plan['tasks'] = [{**copy.deepcopy(first), 'task_id': 'T%d' % i} for i in range(1, 10)]
        tasks = next(d for d in plan['definitions'] if d['kind'] == 'tasks')
        path = check_ref(tasks); path.write_text(''.join('- [ ] T%d implement R1\n' % i for i in range(1, 10))); tasks.update(file_ref(path))
        plan['source_closure']['padding'] = 'x' * 61_000
        f.call('plan', {'plan_ref': f.ref('wide-plan.json', plan)}, role='spec-designer', module='M001')  # accepted, owing
        summaries = sorted(g['summary'] for g in ledger.status(f.root, 'step', 'M001')['open_issues'] if g['kind'] == 'gap')
        self.assertTrue(any(s.startswith('a leaf plans at most 8 tasks') for s in summaries), summaries)
        self.assertTrue(any(s.startswith('plan over 60 KB') for s in summaries), summaries)


class SignalTests(unittest.TestCase):
    def test_the_audit_reads_back_what_says_a_split_was_too_fine(self):
        s = {'modules': {'M001': {'dependencies': []}, 'M002': {'dependencies': ['M001'], 'change_request_history': [{}, {}]},
                         'M003': {'dependencies': ['M002']}},
             'issues': {'I1': {'applies_to': ['M003', 'M001']}, 'I2': {'applies_to': ['M003', 'M002']}, 'I3': {'applies_to': ['M003', 'M001']},
                        'I4': {'applies_to': ['M003', 'M004']}, 'I5': {'applies_to': ['M003']}}}
        signals = decomposition.slicing_signals(s)
        self.assertEqual(signals['M003'], {'cross_module_issues': 4, 'change_requests': 0, 'chain_depth': 3, 'large_tasks': [], 'flags': ['cross-module-issues', 'chain-depth']})
        self.assertEqual(signals['M002']['flags'], ['change-request-cascade'])
        self.assertEqual(signals['M001']['flags'], [])
        self.assertEqual(reading.read_hint('a leaf depends only on scaffold leaves; features do not depend on each other'),
                         {'ref': 'skills/migration-protocol/references/module-decomposition.md', 'section': '切片标准'})


if __name__ == '__main__':
    unittest.main()
