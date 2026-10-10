"""What a revision costs is in proportion to what it changes: a leaf's reports and plan stand on its own slice, the parents
above it and the slices it depends on; a re-split tells each child it keeps what moved; a global plan is accepted over who
holds what, not over how a review words it."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_ledger
import test_decomposition
import context_readiness as cr
import decomposition as dc
import design_stage
from contracts import digest


class StandingTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); f.split(f.proposal(dependencies={'M002': ['M001']})); f.global_plan()
        f.call('register', {'module_id': 'M020', 'name': 'Orders', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'orders')],
                            'dependencies': []}, role='global-orchestrator', module=None)

    def bound(self, state, mid):
        module = state['modules'][mid]
        return cr.subject(state, mid, 'planning'), dc.context_binding(state, module), design_stage.subject(state, module)

    def test_a_leaf_stands_on_itself_its_parents_and_its_providers(self):
        state = self.f.state()
        full = dc.planning_context(state)
        self.assertEqual(set(full['modules']), {'M001', 'M002', 'M020'})
        provider, dependent = dc.standing(state, 'M001'), dc.standing(state, 'M002')
        self.assertEqual((set(provider['modules']), set(provider['parents'])), ({'M001'}, {'M010'}))
        self.assertEqual((set(dependent['modules']), set(dependent['parents'])), ({'M001', 'M002'}, {'M010'}))
        self.assertEqual({key: value for key, value in provider.items() if key not in ('modules', 'parents', 'dimension_allocations', 'feature_owners')},
                         {key: value for key, value in full.items() if key not in ('modules', 'parents', 'dimension_allocations', 'feature_owners')})
        self.assertEqual(dc.standing(state, 'M010'), full)  # a parent stands on all of it
        self.assertEqual(dc.standing(state, None), full)  # and so does the run
        state['modules']['M020']['decomposition_required'] = True
        self.assertEqual(dc.standing(state, 'M020'), full)  # a module still to be split is a parent

    def test_a_dependency_on_a_parent_is_a_dependency_on_its_slices(self):
        context = {'modules': {mid: {'parent_module_id': parent, 'dependencies': dependencies} for mid, parent, dependencies in (
            ('A1', 'A', []), ('A2', 'A', []), ('B1', 'B', ['A']), ('C1', 'C', []))},
            'parents': {'A': ['A1', 'A2'], 'B': ['B1'], 'C': ['C1'], 'ROOT': ['B']}, 'global_spec': 'spec',
            'feature_owners': {'F1': ['A2'], 'F2': ['C1'], 'F3': ['B1', 'C1']}}
        scoped = dc.standing({'modules': {}}, 'B1', context)
        self.assertEqual((set(scoped['modules']), set(scoped['parents'])), ({'A1', 'A2', 'B1'}, {'A', 'B', 'ROOT'}))
        self.assertEqual((set(scoped['feature_owners']), scoped['global_spec']), ({'F1', 'F3'}, 'spec'))

    def test_what_concerns_only_other_slices_leaves_a_leaf_as_it_was(self):
        state = self.f.state()
        before = {mid: self.bound(state, mid) for mid in ('M001', 'M002')}
        state['modules']['M020'].update(scope={'in': ['Orders, reworded'], 'out': [], 'requirement_ids': ['R1']},
                                        write_paths=[str(self.f.target / 'orders-moved')])
        self.assertEqual({mid: self.bound(state, mid) for mid in ('M001', 'M002')}, before)  # another root was rewritten
        state['modules']['M002']['context_refs'] = [self.f.ref('context-M002-again.md', 'read again')]
        self.assertEqual(self.bound(state, 'M001'), before['M001'])  # a slice that depends on it was rewritten: not its concern
        self.assertTrue(all(now != then for now, then in zip(self.bound(state, 'M002'), before['M002'])))  # the slice itself was

    def test_what_a_leaf_stands_on_still_makes_it_stale(self):
        for change in (lambda s: s['modules']['M001'].update(write_paths=[str(self.f.target / 'm1-moved')]),  # its provider
                       lambda s: s['module_groups']['M010']['children'].append('M003'),  # its parent's split
                       lambda s: s.update(new_architecture=self.f.ref('architecture-revised.md', 'layers revised'))):  # what the run shares
            state = self.f.state()
            before = self.bound(state, 'M002')
            change(state)
            with self.subTest(change=change):
                self.assertTrue(all(now != then for now, then in zip((self.bound(state, 'M002'))[:2], before[:2])))

    def test_a_step_hands_a_leaf_what_it_stands_on_and_names_the_rest(self):
        f = self.f
        view = ledger.status(f.root, 'step', 'M002')
        self.assertEqual(view['step']['operation'], 'plan')
        context = view['planning_context']
        self.assertEqual(set(context['modules']), {'M001', 'M002'})
        self.assertEqual(context['other_modules'], {'M020': {'name': 'Orders', 'write_paths': [str(f.target / 'orders')], 'dependencies': []}})
        state = f.state()
        self.assertEqual({key: value for key, value in context.items() if key != 'other_modules'}, dc.standing(state, 'M002'))
        self.assertNotIn('other_modules', ledger.status(f.root, 'step', None).get('planning_context', {}))  # the run's own step is whole


class ResplitTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split(); f.global_plan()

    def resplit(self, change):
        f = self.f
        proposal = f.proposal(); change(proposal)
        f.call('realloc-request', {'reason': 'the slice needs its boundary corrected', 'evidence_refs': [f.ref('need.md', 'read the source')]}, module='M001')
        f.call('redecompose', {'plan_ref': f.ref('resplit-%d.json' % f.n, proposal)}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('resplit-review-%d.md' % f.n, 'reviewed')}, role='global-orchestrator', module='M010')

    def test_a_child_a_re_split_keeps_is_told_what_moved_until_it_plans_again(self):
        f = self.f
        self.resplit(lambda proposal: proposal['children'][0]['scope'].update({'in': ['subfunction-M001', 'one more behavior']}))
        state = f.state()
        self.assertEqual(state['modules']['M001']['allocation_changes'], {'fields': ['scope']})
        self.assertNotIn('allocation_changes', state['modules']['M002'])  # its allocation is the one it had
        self.assertEqual(ledger.status(f.root, 'step', 'M001')['module']['allocation_changes'], {'fields': ['scope']})
        plan = f.plan(); plan['module_id'] = 'M001'
        f.call('plan', {'plan_ref': f.ref('plan-after-resplit.json', plan)}, role='spec-designer', module='M001')
        self.assertNotIn('allocation_changes', f.state()['modules']['M001'])  # planned against the allocation as it is now

    def test_the_delta_names_the_items_and_contracts_of_a_rewritten_analysis(self):
        import dimensions
        calls = []
        originals = dimensions.revised, dimensions.load
        dimensions.revised = lambda before, after, mid: calls.append((before, after, mid)) or ({'ITEM-2'}, {'API-1'})
        dimensions.load = lambda ref, mid: ({}, {'ITEM-1': {}, 'ITEM-2': {}} if ref == 'old' else {'ITEM-1': {}, 'ITEM-2': {}, 'ITEM-9': {}})
        self.addCleanup(lambda: [setattr(dimensions, name, value) for name, value in zip(('revised', 'load'), originals)])
        old = {'module_id': 'M001', 'name': 'a', 'scope': {'in': ['x']}, 'dimension_analysis_ref': 'old'}
        new = {**copy.deepcopy(old), 'dimension_analysis_ref': 'new'}
        self.assertEqual(dc.allocation_delta(old, new), {'fields': ['dimension_analysis_ref'], 'items': ['ITEM-2', 'ITEM-9'], 'apis': ['API-1']})
        self.assertEqual(calls, [('old', 'new', 'M001')])
        self.assertEqual(dc.allocation_delta(old, copy.deepcopy(old)), {'fields': []})

    def test_a_global_plan_is_accepted_over_who_holds_what_not_over_how_it_is_worded(self):
        review = {'shared_capabilities': [{'capability': 'session', 'owner_module_id': 'M001'}], 'summary': 'first wording',
                  'evidence_refs': ['a.md'],
                  'verification': {'acceptance_owner': 'M001', 'case_ids': ['C1'], 'integration_case_ids': [], 'fixture': 'a stub server',
                                   'provider_inputs': [{'module_id': 'M002', 'required_stage': 'coded', 'contract_ref': 'c1.md'}]}}
        module = {'case_ids': ['C1'], 'dependencies': ['M002'], 'write_paths': ['/t/m1'], 'scope': {'in': ['x']}, 'behavior_review': review}
        state = lambda **changes: {'modules': {'M001': {**copy.deepcopy(module), **changes}}}
        held = dc.accepted_over(state())
        reworded = copy.deepcopy(review)
        reworded.update(summary='second wording', evidence_refs=['b.md'])
        reworded['verification'].update(fixture='an in-memory stub')
        reworded['verification']['provider_inputs'][0]['contract_ref'] = 'c2.md'
        self.assertEqual(dc.accepted_over(state(behavior_review=reworded)), held)
        for moved in ({'case_ids': ['C1', 'C2']}, {'dependencies': []}, {'write_paths': ['/t/elsewhere']}, {'scope': {'in': ['y']}}):
            with self.subTest(moved=moved):
                self.assertNotEqual(dc.accepted_over(state(**moved)), held)
        for path, value in ((('shared_capabilities',), []), (('verification', 'acceptance_owner'), 'M002'), (('verification', 'case_ids'), []),
                            (('verification', 'provider_inputs', 0, 'required_stage'), 'completed')):
            changed = copy.deepcopy(review)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path):
                self.assertNotEqual(dc.accepted_over(state(behavior_review=changed)), held)


if __name__ == '__main__':
    unittest.main()
