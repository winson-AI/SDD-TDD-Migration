"""Slices are worked in waves: what depends on nothing first, what depends on it once its first version is there. A parent
states scope and meaning; where things land in the target, the fixture and what a provider offers are the leaf's."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import api_contract
import behavior_contract
import dimensions
import ledger
import test_ledger
import test_decomposition
import test_dimensions
import test_behavior_contract
import test_progressive_fidelity
from contracts import Rejected


def leaf(mid, *dependencies, **state):
    return {'module_id': mid, 'dependencies': list(dependencies), 'phase': 'context', 'stale': True, **state}


class WaveTests(unittest.TestCase):
    def test_a_leaf_comes_one_wave_after_the_last_slice_it_depends_on(self):
        s = {'modules': {'M001': leaf('M001'), 'M002': leaf('M002', 'M001'), 'M003': leaf('M003', 'M001'),
                         'M004': leaf('M004', 'M002', 'M003'), 'M005': leaf('M005', 'G1'), 'M006': leaf('M006')},
             'module_groups': {'G1': {'children': ['M002', 'M003']}}}
        self.assertEqual({mid: ledger.wave(s, mid) for mid in s['modules']},
                         {'M001': 1, 'M002': 2, 'M003': 2, 'M004': 3, 'M005': 3, 'M006': 1})  # a group counts as its leaves

    def test_what_a_leaf_plans_against_is_there_once_it_is_written_or_verified(self):
        tasks = {'plan': {'tasks': [{'task_id': 'T1'}, {'task_id': 'T2'}]}}
        needs = lambda stage: {'behavior_review': {'verification': {'provider_inputs': [{'module_id': 'M001', 'required_stage': stage}]}}}

        def ready(provider, stage):
            s = {'modules': {'M001': leaf('M001', **provider), 'M002': leaf('M002', 'M001', **needs(stage))}, 'module_groups': {}}
            row, = ledger.providers(s, s['modules']['M002'])
            self.assertEqual((row['module_id'], row['required_stage']), ('M001', stage))
            return row['ready']
        self.assertFalse(ready({**tasks}, 'implemented'))
        self.assertFalse(ready({**tasks, 'code_baseline': 'c1', 'accepted_task_ids': ['T1']}, 'implemented'))       # half of it
        self.assertTrue(ready({**tasks, 'code_baseline': 'c1', 'accepted_task_ids': ['T1', 'T2']}, 'implemented'))  # its code, not its tests
        self.assertFalse(ready({**tasks, 'code_baseline': 'c1', 'accepted_task_ids': ['T1', 'T2']}, 'verified'))
        self.assertTrue(ready({**tasks, 'phase': 'completed', 'stale': False}, 'verified'))
        s = {'modules': {'M001': leaf('M001'), 'M002': leaf('M002', 'M001')}, 'module_groups': {}}
        self.assertEqual(ledger.providers(s, s['modules']['M002'])[0]['required_stage'], 'verified')  # unless the split says its code is enough

    def split(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope(); f.split(f.proposal(dependencies={'M002': ['M001']})); f.global_plan()
        return f

    def steps(self, f):
        return {step['module_id']: step for step in f.state()['next_steps']}

    def test_the_cursor_offers_a_dependents_planning_once_its_provider_is_there(self):
        f = self.split()
        steps = self.steps(f)
        self.assertEqual((steps['M001']['operation'], steps['M001']['ready'], steps['M001']['wave']), ('plan', True, 1))
        self.assertEqual((steps['M002']['operation'], steps['M002']['ready'], steps['M002']['reason'], steps['M002']['waiting_for'], steps['M002']['wave']),
                         ('plan', False, 'provider-first-version-pending', ['M001'], 2))
        row, = ledger.status(f.root, 'step', 'M002')['providers']
        self.assertEqual((row['module_id'], row['ready'], row['plan_ref']), ('M001', False, None))
        self.assertNotIn('providers', ledger.status(f.root, 'step', 'M001'))
        f.prepare_leaf('M001'); f.complete_leaf('M001')
        step = self.steps(f)['M002']
        self.assertEqual((step['operation'], step['ready'], step.get('waiting_for')), ('plan', True, None))
        row, = ledger.status(f.root, 'step', 'M002')['providers']
        self.assertEqual((row['ready'], row['plan_ref'], bool(row['code_baseline'])),
                         (True, f.state()['modules']['M001']['plan_ref'], True))  # what it plans against: the provider's plan and code

    def test_a_plan_submitted_before_its_provider_is_there_is_still_judged(self):
        f = self.split()
        plan = f.plan(); plan['module_id'] = 'M002'; plan['paths'][0]['path_id'] = 'P2'; plan['tasks'][0]['path_ids'] = ['P2']
        f.attach_reuse(plan)
        f.call('plan', {'plan_ref': f.ref('early-plan.json', plan)}, role='spec-designer', module='M002')  # this orders the work; it refuses nothing
        self.assertEqual(f.state()['modules']['M002']['phase'], 'clarifying')


class AllocationTests(unittest.TestCase):
    """An allocation states scope and meaning. Where an item lands in the target, how a resource is converted and who
    consumes it are the leaf's: left empty they are accepted, filled by the leaf, and required before freeze."""
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)

    def analysis(self, *dropped):
        analysis = self.d.analysis('M010', kinds=('Logic', 'Resource'))
        for row in analysis['dimensions']:
            for item in row['items']:
                for field in dropped:
                    item.pop(field, None)
        return analysis

    def test_an_allocation_may_leave_the_target_side_to_its_leaf(self):
        open_fields = ('target_binding', 'target_resource', 'consumer', 'conversion')
        allocated = self.analysis(*open_fields)
        dimensions.judge(self.d.f.ref('open-analysis.json', allocated), 'M010')
        with self.assertRaisesRegex(Rejected, r'M010-Logic: the plan settles target_binding before freeze'):
            dimensions.settled(allocated)
        refined = self.analysis()  # the leaf read the source and the target: it fills what was left open
        dimensions.keeps(allocated, refined)
        dimensions.settled(refined)
        partly = self.analysis('consumer', 'conversion')
        with self.assertRaisesRegex(Rejected, r'M010-Resource: the plan settles consumer, conversion before freeze'):
            dimensions.settled(partly)
        changed = copy.deepcopy(refined)
        changed['dimensions'][1]['items'][0]['acceptance'] = 'something easier'
        with self.assertRaisesRegex(Rejected, 'refined analysis changes'):  # what the allocation does state stays
            dimensions.keeps(allocated, changed)

    def test_what_an_allocation_still_states_of_every_item(self):
        for field in ('behavior', 'source_locator', 'target_strategy', 'acceptance'):
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, 'dimension item needs source, behavior, target strategy and acceptance'):
                dimensions.judge(self.d.f.ref('no-' + field + '.json', self.analysis(field)), 'M010')
        with self.assertRaisesRegex(Rejected, 'resource mapping missing source_resource'):
            dimensions.judge(self.d.f.ref('no-source.json', self.analysis('source_resource')), 'M010')

    def test_a_plan_drafted_on_an_open_allocation_takes_what_is_there_and_leaves_the_rest_to_its_author(self):
        import minimal_plan
        ref = self.d.f.ref('open-allocation.json', self.analysis('target_binding', 'target_resource', 'consumer', 'conversion'))
        boundary = {'acceptance_owner': 'M010', 'independent_observation': 'its own result', 'fixture_contract_ref': None, 'case_ids': ['C1']}
        module = {'module_id': 'M010', 'dimension_analysis_ref': ref, 'case_ids': ['C1'], 'behavior_review': {'verification': boundary}}
        own = self.d.f.ref('leaf-fixture.md', 'fixed inputs written by the leaf')
        plan = minimal_plan.complete({}, module, {'source_closure': {'verification': {'fixture_contract_ref': own}}, 'tasks': [], 'paths': []})
        self.assertEqual(plan['source_closure']['verification'], {**boundary, 'fixture_contract_ref': own})  # the author wrote its fixture only
        self.assertEqual(plan['source_closure']['production_binding'], '')  # nothing to derive: the leaf settles where things land


class FixtureTests(unittest.TestCase):
    """The fixed inputs and stand-ins a slice is verified against are test design: the leaf states them when its
    allocation does not, and a contract document about a provider is optional."""
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        self.plan, self.module = test_behavior_contract.contract_plan(f)
        self.boundary = copy.deepcopy(self.plan['source_closure']['verification'])  # the allocation's, as the plan repeats it

    def test_a_split_need_not_name_a_fixture_or_a_contract_document(self):
        module = {**self.module, 'dependencies': ['M002']}
        module['behavior_review'] = {'verification': test_behavior_contract.review(self.f, module)['verification']}
        behavior_contract.verification(module)
        module['behavior_review']['verification'].update(fixture_contract_ref=None, provider_inputs=[{'module_id': 'M002', 'required_stage': 'implemented'}])
        behavior_contract.verification(module)  # what it needs of M002 is M002's accepted code
        module['behavior_review']['verification']['provider_inputs'][0]['contract_ref'] = {'path': '/missing.md', 'sha256': '0' * 64}
        with self.assertRaises(Rejected):  # a document that is named is still checked
            behavior_contract.verification(module)
        module['behavior_review']['verification']['provider_inputs'][0]['required_stage'] = 'planned'
        with self.assertRaisesRegex(Rejected, 'provider stage must be implemented or verified'):
            behavior_contract.verification(module)

    def test_the_leaf_states_the_fixture_its_allocation_left_open_and_binds_its_paths_to_it(self):
        open_boundary = {**copy.deepcopy(self.boundary), 'fixture_contract_ref': None}
        own = self.f.ref('leaf-fixture.md', 'fixed inputs and the stand-in for the provider, written by the leaf')
        plan = copy.deepcopy(self.plan)
        plan['source_closure']['verification'] = {**copy.deepcopy(open_boundary), 'fixture_contract_ref': own}
        plan['paths'][0]['fixture_contract_ref'] = own
        behavior_contract.fixture_bound(open_boundary, plan, settled=True)
        plan['paths'][0]['fixture_contract_ref'] = self.boundary['fixture_contract_ref']
        with self.assertRaisesRegex(Rejected, 'behavior PATH must bind its verification fixture'):
            behavior_contract.fixture_bound(open_boundary, plan)
        draft = copy.deepcopy(self.plan)
        draft['source_closure']['verification'] = copy.deepcopy(open_boundary); draft['paths'][0]['fixture_contract_ref'] = None
        behavior_contract.fixture_bound(open_boundary, draft)  # planned without it
        with self.assertRaisesRegex(Rejected, 'the plan states its verification fixture before freeze'):
            behavior_contract.fixture_bound(open_boundary, draft, settled=True)

    def test_what_the_allocation_states_of_the_boundary_stays(self):
        behavior_contract.fixture_bound(self.boundary, self.plan, settled=True)  # an allocation that names the fixture: bound as before
        plan = copy.deepcopy(self.plan)
        plan['source_closure']['verification']['independent_observation'] = 'something easier to observe'
        with self.assertRaisesRegex(Rejected, 'leaf plan verification differs from allocation'):
            behavior_contract.fixture_bound(self.boundary, plan)
        plan = copy.deepcopy(self.plan)
        plan['source_closure']['verification']['fixture_contract_ref'] = self.f.ref('another.md', 'another fixture')
        with self.assertRaisesRegex(Rejected, 'leaf plan verification differs from allocation'):
            behavior_contract.fixture_bound(self.boundary, plan)


class ApiTargetTests(unittest.TestCase):
    """A call is recorded with its source and its fidelity when a slice is allocated; how the target makes it and what
    it is tested against are settled by the leaf before freeze."""
    def setUp(self):
        self.a = a = test_progressive_fidelity.ApiContractTests(); a.setUp(); self.addCleanup(a.doCleanups)

    def inventory(self, name, **contract):
        row = {**copy.deepcopy(self.a.contract), **contract}
        return {'module_id': 'M001', 'api_inventory_ref': self.a.f.ref(name, {
            'schema_version': 1, 'module_id': 'M001', 'calls': [self.a.source], 'contracts': [row], 'exclusions': []})}

    def test_an_allocated_call_may_leave_its_target_side_and_fixture_to_the_leaf(self):
        allocated = self.inventory('allocated.json', target=None, fixture_contract_ref=None)
        api_contract.load(allocated, self.a.items)
        api_contract.plan(allocated, self.a.items, self.a.plan())  # the obligations come from the source: a plan can cover them already
        settled = self.inventory('settled.json')
        dimensions.keeps(allocated, settled)
        for change, message in (({'fidelity': 'approved-adaptation', 'alternative': 'v2', 'reason': 'x'}, 'changes analysis.api_inventory_ref$'),
                                ({'api_id': 'OTHER'}, 'changes analysis.api_inventory_ref$')):
            with self.subTest(change=change), self.assertRaisesRegex(Rejected, message):
                dimensions.keeps(allocated, self.inventory('changed.json', **change))
        with self.assertRaisesRegex(Rejected, 'changes analysis.api_inventory_ref$'):  # what an allocation states of the target stays
            dimensions.keeps(settled, self.inventory('reopened.json', target=None))

    def test_before_freeze_the_call_has_its_target_side_and_its_fixture(self):
        scope = [str(self.a.f.target / 'm1')]
        for name, contract in (('no-target.json', {'target': None}), ('no-fixture.json', {'fixture_contract_ref': None})):
            self.a.names = __import__('itertools').count()
            complete = self.a.d.analysis('M001'); complete.update(self.inventory(name, **contract))
            complete['api_review'].update(status='applicable', discovery_refs=[self.a.source['source_ref']])
            next(row for row in complete['dimensions'] if row['dimension'] == 'Logic')['items'][0]['api_ids'] = ['QUERY']
            module = {'module_id': 'M001', 'plan_hash': 'frozen-plan', 'write_paths': scope,
                      'plan': {'dimension_analysis_ref': self.a.f.ref('dimensions-' + name, complete)}}
            with self.subTest(name=name), self.assertRaisesRegex(Rejected, "QUERY: the plan settles an API contract's target side and fixture before freeze"):
                api_contract.freeze({'decisions': {}}, module, {})


if __name__ == '__main__':
    unittest.main()
