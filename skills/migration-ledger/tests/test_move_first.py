"""Leaves move as soon as they can: a budget says how many at once, a human decides a thing once, a case has one holder,
and a revised parent sends back only the children that cite what changed."""
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import api_contract
import audit_closure
import behavior_contract
import decomposition
import dimensions
import project_context
import run_changes
from contracts import Rejected, digest
import test_control_policy
import test_dimensions
import test_ledger
import test_progressive_fidelity
import test_run_changes


def leaf(*dependencies, busy=False):
    return {'dependencies': list(dependencies), 'assignments': {'A': {'closed': not busy}} if busy else {}}


class ParallelBudgetTests(unittest.TestCase):
    def state(self, limit=5, **busy):
        modules = {'M002': leaf(), **{mid: leaf('M002') for mid in ('M003', 'M004', 'M005', 'M006', 'M007')},
                   'M008': leaf('M002', 'M003', 'M004', 'M005', 'M006', 'M007')}
        for mid in busy:
            modules[mid] = leaf(*modules[mid]['dependencies'], busy=True)
        return {'modules': modules, 'max_parallel_modules': limit}

    def steps(self, *ready, waiting=()):
        return [{'module_id': mid, 'ready': True} for mid in ready] + [{'module_id': mid, 'ready': False} for mid in waiting]

    def test_a_host_starts_as_many_leaves_as_the_budget_allows_providers_first(self):
        every = ('M008', 'M007', 'M006', 'M005', 'M004', 'M003', 'M002')  # whatever order the cursor lists them in
        self.assertEqual(audit_closure.start_modules(self.state(), self.steps(*every)), ['M002', 'M003', 'M004', 'M005', 'M006'])
        self.assertEqual(audit_closure.start_modules(self.state(limit=2), self.steps(*every)), ['M002', 'M003'])

    def test_a_leaf_that_has_to_wait_gives_its_place_to_the_next(self):
        steps = self.steps('M002', 'M003', 'M005', 'M006', 'M007', 'M008', waiting=('M004',))
        self.assertEqual(audit_closure.start_modules(self.state(), steps), ['M002', 'M003', 'M005', 'M006', 'M007'])

    def test_a_leaf_holding_a_worker_keeps_its_place(self):
        state = self.state(limit=3, M007='worker', M004='worker')
        steps = self.steps('M002', 'M003', 'M005', waiting=('M004', 'M007'))  # a leaf awaiting its worker has no step to take
        self.assertEqual(audit_closure.start_modules(state, steps), ['M004', 'M007', 'M002'])
        self.assertEqual(audit_closure.start_modules(self.state(limit=1, M007='worker', M004='worker'), steps), ['M004', 'M007'])

    def test_a_parent_takes_no_place(self):
        steps = self.steps('M001', 'M002')  # the parent's own step is not a leaf at work
        self.assertEqual(audit_closure.start_modules(self.state(), steps), ['M002'])

    def test_five_leaves_at_once_unless_the_project_says_otherwise(self):
        self.assertEqual(project_context.BUDGETS['max_parallel_modules'], 5)
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        rounds = f.state()['module_rounds']
        self.assertEqual((f.state()['max_parallel_modules'], rounds['parallel_limit']), (5, 5))
        self.assertEqual(rounds['start_modules'], ['M001'])  # its plan can be written before the global review


class AdaptationDecisionTests(unittest.TestCase):
    """A human decides an adaptation once, for the contract; every leaf that holds the contract then freezes without asking."""
    def setUp(self):
        self.a = a = test_progressive_fidelity.ApiContractTests(); a.setUp(); self.addCleanup(a.doCleanups)
        contract = copy.deepcopy(a.contract)
        contract.update(fidelity='approved-adaptation', alternative='client-library', reason='the target ships a client library')
        contract['target']['url'] = '/v2/query'
        complete = a.d.analysis('M001'); complete['api_inventory_ref'] = a.analysis(contract)['api_inventory_ref']
        complete['api_review'].update(status='applicable', discovery_refs=[a.source['source_ref']])
        next(row for row in complete['dimensions'] if row['dimension'] == 'Logic')['items'][0]['api_ids'] = ['QUERY']
        self.ref = a.f.ref('adapted-dimensions.json', complete)
        self.module = {'module_id': 'M001', 'plan': {'dimension_analysis_ref': self.ref, 'decision_envelope': {'allowed_alternatives': ['client-library']}},
                       'plan_hash': 'frozen-plan'}

    def decided(self, **named):
        return {'decisions': {'D': {'kind': 'api-adaptation', 'adaptations': named, 'consumed': False}}}

    def test_what_a_leaf_adapts_is_read_from_its_allocation(self):
        self.assertEqual(api_contract.adaptations(self.module), {'QUERY': 'client-library'})
        self.assertEqual(api_contract.adaptations({'module_id': 'M001', 'dimension_analysis_ref': self.ref}), {'QUERY': 'client-library'})
        self.assertEqual(api_contract.adaptations({'module_id': 'M001'}), {})

    def test_a_decision_that_names_the_contract_and_its_alternative_lets_the_leaf_freeze_on_its_review(self):
        with self.assertRaisesRegex(Rejected, 'kind api-adaptation naming: QUERY'):
            api_contract.freeze({'decisions': {}}, self.module, {'review_ref': self.a.fixture})
        api_contract.freeze(self.decided(QUERY='client-library'), self.module, {'review_ref': self.a.fixture})
        for other in ({'QUERY': 'another-route'}, {'OTHER': 'client-library'}):  # a different adaptation was decided
            with self.subTest(other=other), self.assertRaisesRegex(Rejected, 'API adaptation requires'):
                api_contract.freeze(self.decided(**other), self.module, {'review_ref': self.a.fixture})

    def test_the_parents_approved_envelope_covers_the_adaptation_it_lists(self):
        module = {**self.module, 'parent_module_id': 'P1'}
        envelope = self.a.f.ref('envelope.json', {'parent_module_id': 'P1', 'children': {'M001': module['plan']['decision_envelope']}})
        state = {'decisions': {'B': {'kind': 'batch-envelope', 'module_id': 'P1', 'envelope_ref': envelope}}}
        api_contract.freeze(state, module, {'decision_id': 'B', 'review_ref': self.a.fixture})
        module['plan']['decision_envelope'] = {'allowed_alternatives': ['client-library', 'something-else']}
        with self.assertRaisesRegex(Rejected, 'API adaptation requires'):  # not the envelope a human approved
            api_contract.freeze(state, module, {'decision_id': 'B', 'review_ref': self.a.fixture})

    def test_a_decision_names_only_what_the_run_registered_and_hashes_it(self):
        state = {'modules': {'M001': {'module_id': 'M001', 'dimension_analysis_ref': self.ref}}, 'decisions': {}}
        self.assertEqual(api_contract.registered(state), {'QUERY': 'client-library'})
        named = {'QUERY': 'client-library'}
        api_contract.decision(state, {'module_id': None, 'adaptations': named, 'subject_sha256': digest(named)})
        for bad, reason in (({'adaptations': {'QUERY': 'another-route'}}, 'has not registered'), ({'adaptations': {'OTHER': 'x'}}, 'has not registered'),
                            ({'adaptations': {}}, 'names contracts'), ({'module_id': 'M001'}, 'names contracts'), ({'subject_sha256': 'x'}, 'must hash')):
            payload = {'module_id': None, 'adaptations': named, 'subject_sha256': digest(named), **bad}
            if 'adaptations' in bad and bad['adaptations']:
                payload['subject_sha256'] = digest(bad['adaptations'])
            with self.subTest(bad=bad), self.assertRaisesRegex(Rejected, reason):
                api_contract.decision(state, payload)
        child = {'module_id': 'M002', 'parent_module_id': 'M001', 'dimension_analysis_ref': {'path': '/nowhere', 'sha256': '0'}}
        self.assertEqual(api_contract.registered({**state, 'modules': {**state['modules'], 'M002': child}}), named)  # a child's contracts are its parent's


class AdaptationStepTests(unittest.TestCase):
    """The cursor asks once, for every adaptation the run still has open, instead of offering a freeze the gate refuses."""
    def setUp(self):
        self.c = c = test_control_policy.ControlPolicyTests(); c.setUp(); self.addCleanup(c.doCleanups)
        self.f = f = c.f
        f.global_plan()
        f.call('plan', {'plan_ref': f.ref('policy-plan.json', f.plan())}, role='spec-designer')
        f.call('plan-review', {'review_ref': c.review()})
        self.open = {'QUERY': 'client-library', 'UPLOAD': 'client-library'}
        for name, value in (('adaptations', lambda module: {'QUERY': 'client-library'}), ('registered', lambda s: dict(self.open))):
            patch = mock.patch.object(api_contract, name, side_effect=value); patch.start(); self.addCleanup(patch.stop)

    def step(self):
        return self.f.state()['next_steps'][0]

    def test_a_leaf_with_an_open_adaptation_waits_for_one_decision_that_names_them_all(self):
        f = self.f; step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['reason'], step['human_required']), ('freeze', False, 'human-decision-required', True))
        self.assertEqual((step['approval_kind'], step['adaptations'], step['approval_subject_sha256']), ('api-adaptation', self.open, digest(self.open)))
        with self.assertRaisesRegex(Rejected, 'API adaptation requires'):
            f.call('freeze', step['payload'])
        f.call('decision', {'decision_id': 'ADAPT', 'decision': 'approved', 'kind': 'api-adaptation', 'module_id': None,
                            'adaptations': step['adaptations'], 'subject_sha256': step['approval_subject_sha256'],
                            'human_source_ref': f.ref('adaptation.md', 'the task owner chose the client library for these calls')},
               role='host', module=None)
        step = self.step()
        self.assertEqual((step['operation'], step['ready'], step['human_required']), ('freeze', True, False))
        self.assertNotIn('adaptations', step)
        f.call('freeze', step['payload'])
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')
        self.assertFalse(f.state()['decisions']['ADAPT']['consumed'])  # it stands for the next leaf that holds these contracts

    def test_a_leaf_without_adaptations_is_asked_nothing(self):
        with mock.patch.object(api_contract, 'adaptations', side_effect=lambda module: {}):
            step = self.step()
            self.assertEqual((step['operation'], step['ready'], step['human_required']), ('freeze', True, False))


class OneHolderTests(unittest.TestCase):
    """Overlapping slices are not a split: a slice that accepts cases holds exactly those."""
    def child(self, mid, held, accepted=()):
        return {'module_id': mid, 'case_ids': list(held), 'acceptance_case_ids': list(accepted)}

    def judge(self, children, judged=None):
        parent = {'module_id': 'M010', 'case_ids': ['C1', 'C2', 'C3']}
        plan = {'case_acceptance': {cid: child['module_id'] for child in children for cid in child['acceptance_case_ids']},
                'supporting_slices': {child['module_id']: 'a provider every slice uses' for child in children if not child['acceptance_case_ids']}}
        return behavior_contract.independence(parent, children, {child['module_id']: [] for child in children}, plan, (), judged)

    def test_slices_that_each_hold_what_they_accept_share_nothing(self):
        shape = self.judge([self.child('M001', ['C1', 'C2'], ['C1', 'C2']), self.child('M002', ['C3'], ['C3'])])
        self.assertEqual(shape['shared_cases'], [])

    def test_a_slice_that_accepts_cases_cannot_also_hold_another_slices_case(self):
        children = [self.child('M001', ['C1', 'C2', 'C3'], ['C1', 'C2']), self.child('M002', ['C3'], ['C3'])]
        with self.assertRaisesRegex(Rejected, 'a case has one holder: M001 also holds C3'):
            self.judge(children)
        self.judge(children, judged={'M002'})  # a slice the Ledger already holds is not judged again by a re-split
        with self.assertRaisesRegex(Rejected, 'a case has one holder: M001 also holds C3'):
            self.judge(children, judged={'M001', 'M002'})

    def test_only_a_slice_that_accepts_nothing_holds_the_cases_of_the_slices_it_serves(self):
        shape = self.judge([self.child('M001', ['C1', 'C2', 'C3'], ['C1', 'C2', 'C3']), self.child('M002', ['C1', 'C3'])])
        self.assertEqual((shape['supporting'], shape['shared_cases']), (['M002'], ['C1', 'C3']))  # stated, and visible in the report


class ItemCaseTests(unittest.TestCase):
    """What a child holds and cites of a parent item stays attached to it; a case another child holds is that child's."""
    PARENT = {'module_id': 'M010', 'dimension_analysis_ref': {'path': '/parent', 'sha256': 'p'}}
    ITEMS = {'P-UI': {'dimension': 'UI', 'requirement_ids': ['R1'], 'case_ids': ['C1', 'C2']},
             'P-LOGIC': {'dimension': 'Logic', 'requirement_ids': ['R1'], 'case_ids': ['C2']}}

    def partition(self, **children):
        """children: {module id: {item id: (parent item id, case ids)}}; a child holds the cases of its items."""
        items = {mid: {iid: {'dimension': self.ITEMS[pid]['dimension'], 'requirement_ids': ['R1'], 'case_ids': list(cases), 'parent_item_ids': [pid]}
                       for iid, (pid, cases) in rows.items()} for mid, rows in children.items()}
        proposal = {'dimension_partition_review_ref': {}, 'children': [
            {'module_id': mid, 'dimension_analysis_ref': {'path': '/' + mid, 'sha256': mid},
             'case_ids': sorted({cid for item in rows.values() for cid in item['case_ids']})} for mid, rows in items.items()]}
        allocation = lambda s, module: self.ITEMS if module['module_id'] == 'M010' else items[module['module_id']]
        with mock.patch.object(dimensions, 'allocation', side_effect=allocation), mock.patch.object(dimensions, 'check_ref'), \
                mock.patch.object(dimensions, 'read_json', return_value={}), mock.patch.object(api_contract, 'read', return_value=({}, {})), \
                mock.patch.object(dimensions, 'load', side_effect=lambda ref, mid: ({'parent_ref': self.PARENT['dimension_analysis_ref']}, None)):
            dimensions.partition({}, self.PARENT, proposal)

    def test_a_case_of_the_item_held_by_another_slice_is_carried_by_its_holder(self):
        self.partition(M001={'A-UI': ('P-UI', ['C1'])}, M002={'B-LOGIC': ('P-LOGIC', ['C2'])})  # C2 of the screen item is M002's case

    def test_a_case_a_citing_child_holds_stays_attached_to_what_it_cites(self):
        with self.assertRaisesRegex(Rejected, 'omit parent item requirements/cases'):
            self.partition(M001={'A-UI': ('P-UI', ['C1']), 'A-LOGIC': ('P-LOGIC', ['C2'])})  # it holds C2 and cites the screen item without it
        self.partition(M001={'A-UI': ('P-UI', ['C1', 'C2']), 'A-LOGIC': ('P-LOGIC', ['C2'])})


class CarriedChildrenTests(unittest.TestCase):
    """A revised parent sends back only the children that cite what it changed; the others stand and keep moving."""
    LOGIC, ADHESIVE, RESOURCE = 1, 2, 3  # rows of an analysis, in its fixed order

    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        self.f = f = d.f
        d.root(('Logic', 'Resource'))
        self.plan = plan = d.proposal(ids=('M001', 'M002'))
        self.held = {'M001': f.ref('M001-logic.json', d.analysis('M001', ('Logic',), d.root_ref)),  # cites the parent's logic item
                     'M002': f.ref('M002-resource.json', d.analysis('M002', ('Resource',), d.root_ref))}  # cites its resource item
        for child in plan['children']:
            child['dimension_analysis_ref'] = self.held[child['module_id']]
        f.split(plan)

    def root_version(self, change=None, kinds=('Logic', 'Resource')):
        analysis = self.d.analysis(kinds=kinds)
        if change: change(analysis)
        return self.f.ref('root-version-%d.json' % self.f.n, analysis)

    def report(self, root_ref, **actions):
        f = self.f
        root = run_changes.roots(f.state())['M010']
        update = {**{key: copy.deepcopy(root[key]) for key in run_changes.ROOT_KEYS if key in root}, 'dimension_analysis_ref': root_ref}
        proof = f.ref('root-impact.md', 'Compared the revised root item by item with each child')
        return {'schema_version': 1, 'run_id': f.state()['run_id'], 'reason': 'Corrected root analysis', 'context_patch': {},
                'boundary_review': {'semantic_change': True, 'authorization_change': False, 'unresolved_questions': [],
                                    'reason': 'Reviewed which children cite the corrected item', 'evidence_refs': [proof]},
                'root_updates': [update], 'modules': [{'module_id': mid, 'action': action, 'reason': 'Reviewed against the corrected root',
                                                       'evidence_refs': [proof], 'resume_blocker_sha256': None} for mid, action in actions.items()]}

    def apply(self, report):
        f = self.f
        f.call('run-review', {'report_ref': f.ref('run-review-%d.json' % f.n, report)}, role='global-orchestrator', module=None)
        subject = f.state()['run_change_review']['subject_sha256']
        did = 'REV-%d' % f.n
        f.call('decision', {'decision_id': did, 'module_id': None, 'decision': 'approved', 'subject_sha256': subject,
                            'human_source_ref': f.ref(did + '.md', 'Approve this revision')}, role='host', module=None)
        f.call('revise-run', {'decision_id': did, 'subject_sha256': subject}, role='host', module=None)

    def corrected(self, analysis):
        analysis['dimensions'][self.LOGIC]['items'][0]['acceptance'] = 'Corrected observable boundary'

    def reworded_evidence(self, analysis):
        analysis['dimensions'][self.RESOURCE]['items'][0]['evidence_refs'] = [self.f.ref('newer-proof.md', 'The same facts, read again')]

    def step(self, mid):
        return next(row for row in self.f.state()['next_steps'] if row['module_id'] == mid)

    def test_what_a_child_cites_is_compared_without_the_evidence_it_was_written_from(self):
        d = self.d
        self.assertEqual(dimensions.revised(d.root_ref, self.root_version(self.corrected), 'M010'), ({'M010-Logic'}, set()))
        self.assertEqual(dimensions.revised(d.root_ref, self.root_version(self.reworded_evidence), 'M010'), (set(), set()))
        self.assertEqual(dimensions.revised(d.root_ref, self.root_version(kinds=('Logic',)), 'M010'), ({'M010-Resource'}, set()))  # an item that is gone
        parent = {'module_id': 'M010', 'dimension_analysis_ref': self.root_version(self.corrected)}
        touched = lambda mid: dimensions.touched(parent, *dimensions.load(self.held[mid], mid))
        self.assertEqual((touched('M001'), touched('M002')), (['M010-Logic'], []))

    def test_a_revision_names_every_child_that_cites_what_it_changes(self):
        f = self.f; ref = self.root_version(self.corrected)
        with self.assertRaisesRegex(Rejected, r'retained child M001 cites what the revision changes \(M010-Logic\)'):
            run_changes.validate(f.state(), f.ref('everyone-unchanged.json', self.report(ref, M001='unchanged', M002='unchanged')))
        _, affected, changed = run_changes.validate(f.state(), f.ref('one-replans.json', self.report(ref, M001='replan', M002='unchanged')))
        self.assertEqual((affected, changed), ({'M001'}, {'M010'}))

    def test_only_the_children_a_revision_reaches_wait_for_the_resplit(self):
        f, d = self.f, self.d; ref = self.root_version(self.corrected)
        before = f.state()['modules']['M002']
        self.apply(self.report(ref, M001='replan', M002='unchanged'))
        group = f.state()['module_groups']['M010']
        self.assertEqual((group['replanning_required'], group['replanning_children'], group['dimension_analysis_ref']), (True, ['M001'], ref))
        parent, reached, standing = self.step('M010'), self.step('M001'), self.step('M002')
        self.assertEqual((parent['operation'], parent['reason'], parent['affected_children']), ('redecompose', 'root-allocation-revised', ['M001']))
        self.assertEqual((reached['operation'], reached['reason']), (None, 'allocation-review-required'))
        self.assertEqual((standing['operation'], standing['ready']), ('plan', True))  # it keeps moving while its sibling is written again
        self.assertEqual(f.state()['modules']['M002']['revision'], before['revision'])
        restated = copy.deepcopy(self.plan)
        with self.assertRaisesRegex(Rejected, r'child M001 cites what its parent revised since it was allocated \(M010-Logic\)'):
            f.call('redecompose', {'plan_ref': f.ref('nothing-rewritten.json', restated)}, module='M010')
        restated['children'][0]['dimension_analysis_ref'] = f.ref('M001-logic-again.json', d.analysis('M001', ('Logic',), ref))
        f.call('redecompose', {'plan_ref': f.ref('one-rewritten.json', restated)}, module='M010')
        f.call('redecompose-accept', {'review_ref': f.ref('resplit-review.md', 'M001 written again; M002 stands')}, role='global-orchestrator', module='M010')
        state = f.state(); group = state['module_groups']['M010']
        self.assertNotIn('replanning_required', group); self.assertNotIn('replanning_children', group)
        self.assertEqual(state['redecomposition_history'][-1]['affected_modules'], ['M001'])
        self.assertEqual((state['modules']['M002']['dimension_analysis_ref'], state['modules']['M002']['revision']), (self.held['M002'], before['revision']))
        self.assertEqual((self.step('M001')['operation'], self.step('M002')['operation']), ('plan', 'plan'))

    def test_a_revision_that_changes_nothing_a_child_cites_needs_no_resplit(self):
        f = self.f; ref = self.root_version(self.reworded_evidence)
        self.apply(self.report(ref, M001='unchanged', M002='unchanged'))
        group = f.state()['module_groups']['M010']
        self.assertEqual(group['dimension_analysis_ref'], ref)
        self.assertNotIn('replanning_required', group)
        self.assertEqual([(self.step(mid)['operation'], self.step(mid)['ready']) for mid in ('M001', 'M002')], [('plan', True)] * 2)
        self.assertEqual(self.step('M010')['operation'], None)  # nothing for the parent to write

    def test_work_a_revision_adds_is_given_to_a_leaf(self):
        f = self.f; ref = self.root_version(kinds=('Logic', 'Adhesive', 'Resource'))
        with self.assertRaisesRegex(Rejected, 'adds work no leaf is asked to take: M010-Adhesive'):
            run_changes.validate(f.state(), f.ref('nobody-takes-it.json', self.report(ref, M001='unchanged', M002='unchanged')))
        run_changes.validate(f.state(), f.ref('one-takes-it.json', self.report(ref, M001='replan', M002='unchanged')))

    def test_an_analysis_written_now_binds_the_parents_current_version(self):
        f, d = self.f, self.d; ref = self.root_version(self.reworded_evidence)
        self.apply(self.report(ref, M001='unchanged', M002='unchanged'))
        proposal = copy.deepcopy(self.plan)
        proposal['children'][0]['dimension_analysis_ref'] = f.ref('M001-written-now.json', d.analysis('M001', ('Logic',), d.root_ref))
        with self.assertRaisesRegex(Rejected, 'child dimension parent reference mismatch'):
            f.call('redecompose', {'plan_ref': f.ref('stale-binding.json', proposal)}, module='M010')


class DependentTests(unittest.TestCase):
    """A leaf next to one that plans again is not sent back with it; only code built on that one has to wait."""
    def module(self, mid, dependencies=(), code=False):
        return {'module_id': mid, 'name': mid, 'scope': {'in': [mid], 'out': [], 'requirement_ids': ['R1']}, 'case_ids': ['C-' + mid],
                'write_paths': ['/target/' + mid], 'context_refs': [], 'dimension_analysis_ref': None, 'behavior_review': None,
                'dependencies': list(dependencies), 'freeze_id': None, 'blocked': None, 'code_baseline': {'files': 'built'} if code else None}

    def resplit(self):
        state = {'modules': {'M001': self.module('M001'), 'M002': self.module('M002', ['M001'], code=True),
                             'M003': self.module('M003', ['M001']), 'M004': self.module('M004')}}
        parent = {'module_id': 'M010', 'children': ['M001', 'M002', 'M003', 'M004']}
        children = [copy.deepcopy(module) for module in state['modules'].values()]
        children[0]['scope']['in'] = ['M001, corrected']  # the provider's allocation changes; nobody else's does
        return state, parent, children, {mid: module['dependencies'] for mid, module in state['modules'].items()}

    def test_a_resplit_sends_back_the_child_it_changes_and_nobody_who_depends_on_it(self):
        self.assertEqual(decomposition.revision_plan(*self.resplit()), ({'M001'}, set()))

    def test_it_reaches_the_leaf_that_holds_code_built_on_that_child_and_not_the_one_that_only_plans(self):
        state, parent, children, graph = self.resplit()
        self.assertEqual(decomposition.built_on(state, {'M001'}), {'M002'})
        self.assertEqual(decomposition.redecomposition_impact(state, parent, children, graph), {'M001', 'M002'})

    def test_the_leaf_holding_code_keeps_its_plan_and_waits_for_its_provider(self):
        t = test_run_changes.RootRevisionTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f = t.f; f.prepare_leaf('M002')  # planned, frozen and coded
        before = f.state()['modules']['M002']
        proposal = f.proposal(); proposal['children'][0]['scope']['in'] = ['Corrected M001 boundary']
        with mock.patch.object(decomposition, 'built_on', return_value={'M002'}):  # as if its code were built on M001
            f.call('redecompose', {'plan_ref': f.ref('provider-revision.json', proposal)}, module='M010')
            f.call('redecompose-accept', {'review_ref': f.ref('provider-review.md', 'Only M001 changes')}, role='global-orchestrator', module='M010')
        after = f.state()['modules']['M002']
        self.assertEqual((after['phase'], after['blocked']['reason'], after['blocked']['resume_phase']),
                         ('waiting-dependency', 'dependency-version-changed', 'frozen'))
        self.assertEqual((after['freeze_id'], after['plan_ref'], after['code_baseline']), (before['freeze_id'], before['plan_ref'], before['code_baseline']))
        self.assertIsNone(f.state()['modules']['M001']['freeze_id'])


class LeafBoundConditionTests(unittest.TestCase):
    """Whoever allocates an item records its conditions before any PATH exists; the leaf's plan says which assertions prove them."""
    PATHS = {'P1': {'kind': 'automation', 'expected_assertions': [{'assertion_id': 'A1'}, {'assertion_id': 'A2'}]}}

    def item(self, **condition):
        return {'item_id': 'SCREEN', 'fidelity_conditions': [{'condition_id': 'FONT', 'condition': 'text does not scale with the system font',
                'status': 'applicable', 'reason': 'the legacy sizes are fixed', 'evidence_refs': [{'path': '/source', 'sha256': '0'}],
                'assertions': [], **condition}]}

    def trace(self, **bound):
        return {'item_id': 'SCREEN', 'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}], **({'condition_assertions': bound} if bound else {})}

    def check(self, item, trace):
        with mock.patch.object(dimensions, 'evidence'):
            dimensions.fidelity_conditions(item, self.PATHS, trace)

    def test_the_plan_binds_an_assertion_of_the_item_to_the_condition(self):
        self.check(self.item(), self.trace(FONT=[{'path_id': 'P1', 'assertion_id': 'A1'}]))
        with self.assertRaisesRegex(Rejected, r'fidelity condition FONT assertions \(the trace of SCREEN binds them'):
            self.check(self.item(), self.trace())
        with self.assertRaisesRegex(Rejected, 'item-owned'):  # an assertion the item's trace does not own
            self.check(self.item(), self.trace(FONT=[{'path_id': 'P1', 'assertion_id': 'A2'}]))

    def test_what_the_analysis_already_names_stands(self):
        named = [{'path_id': 'P1', 'assertion_id': 'A1'}]
        self.assertEqual(dimensions.bound(self.item(assertions=named)['fidelity_conditions'][0], self.trace(FONT=[{'path_id': 'P1', 'assertion_id': 'A2'}])), named)
        self.assertEqual(dimensions.bound(self.item()['fidelity_conditions'][0]), [])  # nothing to read before a plan exists
        self.check(self.item(assertions=named), self.trace())

    def test_the_report_reads_the_binding_from_the_plan(self):
        import migration_report
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [self.item()]}]}
        plan = {'dimension_analysis_ref': f.ref('leaf-analysis.json', analysis), 'dimension_trace': [self.trace(FONT=[{'path_id': 'P1', 'assertion_id': 'A1'}])]}
        row = {'module_id': 'M001', 'path_id': 'P1', 'kind': 'automation', 'quality': 'green-passed', 'executed': True, 'attempt_executed': True,
               'stale': False, 'assertions': [{'assertion_id': 'A1', 'passed': True}]}
        from contracts import check_ref
        condition, = migration_report.fidelity({'modules': {'M001': {'plan': plan}}}, [row], check_ref)[2]['conditions']
        self.assertEqual((condition['status'], condition['assertions']), ('verified', [{'path_id': 'P1', 'assertion_id': 'A1'}]))
        plan['dimension_trace'] = [self.trace()]
        condition, = migration_report.fidelity({'modules': {'M001': {'plan': plan}}}, [row], check_ref)[2]['conditions']
        self.assertEqual(condition['status'], 'not-verified')

    def test_a_plan_binds_only_conditions_its_item_carries(self):
        d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f; d.root(); f.split(d.proposal())
        plan = d.leaf_plan()
        plan['dimension_trace'][0]['condition_assertions'] = {'NOT-ALLOCATED': [{'path_id': 'P1', 'assertion_id': 'A1'}]}
        with self.assertRaisesRegex(Rejected, 'condition_assertions names a condition the item does not carry'):
            f.call('plan', {'plan_ref': f.ref('unknown-condition.json', plan)}, role='spec-designer')


if __name__ == '__main__':
    unittest.main()
