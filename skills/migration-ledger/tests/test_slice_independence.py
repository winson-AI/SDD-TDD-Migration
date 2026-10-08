"""Slices of one split stand apart: one slice accepts a case, a supporting slice says why, a chain is argued for."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import behavior_contract
import decomposition
import migration_report
import rule_debt
import test_decomposition
from contracts import Rejected
from test_behavior_contract import review


class LayerTests(unittest.TestCase):
    """A split is read from what each slice's own four-dimension analysis carries."""
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def child(self, mid, accepted=(), **dimensions):
        analysis = {'dimensions': [{'dimension': name, 'status': 'applicable', 'items': [{'item_id': mid + '-' + name, 'case_ids': list(cases)}]}
                                   for name, cases in dimensions.items()]}
        return {'module_id': mid, 'case_ids': ['C1', 'C2'], 'acceptance_case_ids': list(accepted),
                'dimension_analysis_ref': self.f.ref(mid + '-profile.json', analysis)}

    def judge(self, children, **plan):
        parent = {'module_id': 'M010', 'case_ids': ['C1', 'C2']}
        graph = {child['module_id']: [] for child in children}
        supporting = {child['module_id']: 'a provider the accepting slice uses' for child in children if not child['acceptance_case_ids']}
        return behavior_contract.independence(parent, children, graph, {'case_acceptance': {'C1': 'M001', 'C2': 'M001'},
                                                                         'supporting_slices': supporting, **plan})

    def test_a_case_whose_screen_and_logic_live_in_two_slices_is_cut_by_layer(self):
        layered = [self.child('M001', ('C1', 'C2'), UI=['C1', 'C2']), self.child('M002', Logic=['C1', 'C2'], Resource=['C1'])]
        shape = behavior_contract.slicing(layered, {'M001': [], 'M002': []})
        self.assertEqual((shape['layered_cases'], shape['single_layer']), (['C1', 'C2'], ['M001', 'M002']))
        with self.assertRaisesRegex(Rejected, '2 cases have their screen in one slice and their logic in another'):
            self.judge(layered)
        self.judge(layered, independence_review={'rationale': 'the logic is one provider every screen of the product uses',
                                                 'evidence_refs': [self.f.ref('layer-review.md', 'why it cannot live in the screen slice')]})

    def test_a_slice_that_shows_and_decides_its_case_is_vertical(self):
        vertical = [self.child('M001', ('C1', 'C2'), UI=['C1', 'C2'], Logic=['C1', 'C2']), self.child('M002', Logic=['C2'], Adhesive=['C1'])]
        shape = behavior_contract.slicing(vertical, {'M001': [], 'M002': []})
        self.assertEqual((shape['layered_cases'], shape['single_layer']), ([], ['M002']))  # M002 still decides without showing
        self.judge(vertical)

    def test_a_slice_without_a_readable_analysis_is_not_guessed_at(self):
        children = [{'module_id': 'M001', 'case_ids': ['C1', 'C2'], 'acceptance_case_ids': ['C1', 'C2']}, self.child('M002', Logic=['C1'])]
        self.assertEqual(behavior_contract.slicing(children, {'M001': [], 'M002': []})['layered_cases'], [])


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project')

    def proposal(self, ids=('M001', 'M002'), dependencies=None):
        plan = self.f.proposal(ids=ids, dependencies=dependencies)
        for child in plan['children']:
            child['behavior_review'] = review(self.f, child)
        return plan

    def judge(self, plan):
        state = self.f.state()
        return decomposition.validate(state, state['modules']['M010'], plan)

    def test_the_split_names_the_one_slice_that_accepts_each_case(self):
        plan = self.proposal()
        self.assertEqual(plan['case_acceptance'], {'C1': 'M001'})
        children, _ = self.judge(plan)
        self.assertEqual([behavior_contract.accepts(child) for child in children], [['C1'], []])
        for change, message in (
            (lambda p: p.pop('case_acceptance'), 'case_acceptance required'),
            (lambda p: p.update(case_acceptance={}), 'names exactly the cases the parent accepts'),
            (lambda p: p.update(case_acceptance={'C1': 'M009'}), 'accepted by a slice of this split that holds it'),
        ):
            bad = copy.deepcopy(plan); change(bad)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.judge(bad)

    def test_a_slice_that_accepts_no_case_says_why_it_stands_alone(self):
        plan = self.proposal()
        for value in ({}, {'M002': ' '}, {'M001': 'a reason for the wrong slice'}):
            with self.subTest(value=value), self.assertRaisesRegex(Rejected, 'supporting slice.*M002'):
                self.judge({**plan, 'supporting_slices': value})

    def test_a_chain_of_slices_is_argued_for(self):
        plan = self.proposal(ids=('M001', 'M002', 'M003'), dependencies={'M002': ['M001'], 'M003': ['M002']})
        with self.assertRaisesRegex(Rejected, 'chain of 3, 2 of 3 wait'):
            self.judge(plan)
        plan['independence_review'] = {'rationale': 'the third slice renders what the second computes from the first'}
        with self.assertRaisesRegex(Rejected, 'independence review evidence'):
            self.judge(plan)
        plan['independence_review']['evidence_refs'] = [self.f.ref('chain-review.md', 'why the slices cannot be cut by behavior')]
        self.judge(plan)
        self.judge(self.proposal(dependencies={'M002': ['M001']}))  # one slice waiting for another needs no argument

    def test_a_slice_cannot_accept_a_case_a_slice_outside_its_split_accepts(self):
        f = self.f; state = f.state()
        other = copy.deepcopy(state['modules']['M010']); other.update(module_id='M020', decomposition_required=False)
        state['modules']['M020'] = other
        with self.assertRaisesRegex(Rejected, 'outside this split already accepts: C1'):
            decomposition.validate(state, state['modules']['M010'], self.proposal())
        other['acceptance_case_ids'] = []  # the other root holds the case as a contribution
        decomposition.validate(state, state['modules']['M010'], self.proposal())

    def test_acceptance_is_recorded_on_the_slice_and_reaches_its_planner(self):
        f = self.f
        f.split(self.proposal())
        state = f.state()
        self.assertEqual(state['modules']['M001']['acceptance_case_ids'], ['C1'])
        self.assertEqual(state['modules']['M002']['acceptance_case_ids'], [])
        self.assertEqual(decomposition.assigned_module(state, state['modules']['M001'])['acceptance_case_ids'], ['C1'])
        self.assertEqual(behavior_contract.slices(state), [{'parent_module_id': 'M010', 'slices': 2, 'supporting': ['M002'],
            'shared_cases': [], 'accepted_cases': ['C1'], 'chain_depth': 1, 'waiting': 0, 'layered_cases': [], 'single_layer': []}])
        self.assertIn('## 切片独立性', migration_report.render(migration_report.build(f.root, state, 1)))

    def test_moving_acceptance_in_a_resplit_replans_both_slices(self):
        f = self.f
        f.split(self.proposal())
        state = f.state(); parent = state['module_groups']['M010']
        same = self.proposal()
        children, graph = decomposition.validate(state, parent, same, redecompose=True)
        self.assertEqual(decomposition.redecomposition_impact(state, parent, children, graph), set())
        moved = self.proposal(); moved.update(case_acceptance={'C1': 'M002'}, supporting_slices={'M001': 'now a provider of M002'})
        children, graph = decomposition.validate(state, parent, moved, redecompose=True)
        self.assertEqual(decomposition.redecomposition_impact(state, parent, children, graph), {'M001', 'M002'})

    def test_a_registered_split_that_todays_rule_refuses_is_rule_debt(self):
        f = self.f
        f.split(self.proposal())
        state = f.state()
        self.assertNotIn(('M010', 'split'), {(row['module_id'], row['artifact']) for row in rule_debt.collect(state)})
        state['modules']['M002'].pop('acceptance_case_ids')  # as registered before splits named the accepting slice
        self.assertEqual(behavior_contract.slices(state)[0]['shared_cases'], ['C1'])
        self.assertIn(('M010', 'split'), {(row['module_id'], row['artifact']) for row in rule_debt.collect(state)})


class RootTests(unittest.TestCase):
    def test_one_root_accepts_a_case_and_another_holds_it_as_a_contribution(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        old = f.state(); f.root = f.base / 'contract-run'
        payload = {k: old[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec', 'new_architecture')}
        f.call('init', {**payload, 'behavior_contract_required': True, 'dimension_slicing_required': False,
                        'context_readiness_required': False, 'split_testing_required': False}, role='host')

        def root(mid, **extra):
            module = {'module_id': mid, 'scope': {'in': ['query ' + mid], 'out': ['history'], 'requirement_ids': ['R1']},
                      'case_ids': ['C1'], 'write_paths': [str(f.target / mid)], 'context_refs': [f.ref('context.md', 'query sources')], **extra}
            module['behavior_review'] = review(f, module)
            return module
        f.call('register', root('M001'), role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'already accepted by another root: C1'):
            f.call('register', root('M002'), role='global-orchestrator', module=None)
        with self.assertRaisesRegex(Rejected, 'acceptance cases outside allocation'):
            f.call('register', root('M002', acceptance_case_ids=['C2']), role='global-orchestrator', module=None)
        f.call('register', root('M002', acceptance_case_ids=[]), role='global-orchestrator', module=None)
        self.assertEqual(f.state()['modules']['M002']['acceptance_case_ids'], [])


if __name__ == '__main__':
    unittest.main()
