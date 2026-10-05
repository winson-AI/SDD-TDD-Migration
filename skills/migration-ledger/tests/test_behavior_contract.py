"""Scope-first behavior reviews and every-Scenario freezing."""
import copy
import unittest

import test_ledger
import test_decomposition
import behavior_contract as bc
import decomposition
import ledger
import spec_closure
from contracts import Rejected, digest, validate_plan


COPIES = ('scope_sha256', 'requirement_ids', 'case_ids')  # what a review may omit: its allocation states it


def review(f, module):
    return {'scope_sha256': digest(module['scope']), 'entry': 'search input',
            'observable_result': 'result, empty or error', 'production_binding': 'Search route calls repository',
            'boundary_rationale': 'one user-visible query; history remains a separate capability',
            'requirement_ids': module['scope']['requirement_ids'], 'case_ids': module['case_ids'],
            'verification': {'acceptance_owner': module['module_id'], 'independent_observation': module['module_id'] + ' isolated result',
                'isolation_strategy': 'fixed fixture inputs with declared provider doubles', 'integration_responsibility': 'consumer owns live-provider integration',
                'fixture_contract_ref': f.ref('fixture-boundary-' + module['module_id'] + '.md', 'Pinned input state, provider doubles and observable result'),
                'case_ids': module['case_ids'], 'integration_case_ids': [],
                'provider_inputs': [{'module_id': mid, 'required_stage': 'verified', 'contract_ref': f.ref('provider-' + mid + '.md', 'Fixed provider input/output contract')} for mid in module.get('dependencies', [])]},
            'shared_capabilities': [], 'unresolved': [],
            'evidence_refs': [f.ref('behavior-review.md', 'Read legacy entry, target bindings, architecture and dependencies')]}


def contract_plan(f):
    module = copy.deepcopy(f.state()['modules']['M001'])
    module['scope'] = {'in': ['query'], 'out': ['history'], 'requirement_ids': ['R1']}
    plan = f.plan()
    spec = '## ADDED Requirements\n### Requirement: query\nRequirement-ID: R1\nSystem SHALL return query states.\n'
    for name in ('success', 'empty', 'error'):
        spec += f'#### Scenario: {name}\nScenario-ID: SCN-M001-{name}\nWHEN queried THEN render {name}.\n'
    for i, ref in enumerate(plan['definitions']):
        if ref['kind'] == 'spec':
            plan['definitions'][i] = {**f.ref('contract-spec.md', spec), 'kind': 'spec'}
    plan['behavior_contract_required'] = True  # as the Ledger stores it; an author may leave it out
    plan['source_closure'].update(review(f, module))
    path = plan['paths'][0]
    path['kind'] = 'automation'
    path['expected_assertions'] = [{'assertion_id': name, 'expected': name, 'scenario_ids': ['SCN-M001-' + name]}
                                   for name in ('success', 'empty', 'error')]  # the designer says what each one verifies
    plan['paths'].append({'path_id': 'S1', 'name': 'scenario closure', 'kind': 'static', 'case_id': 'C1',
                          'requirement_id': 'R1', 'required': True,
                          'expected_assertions': [{'assertion_id': 'CLOSURE', 'expected': True}]})
    plan['tasks'][0]['path_ids'].append('S1')
    plan['scenario_trace'] = [{'scenario_id': 'SCN-M001-' + name, 'task_ids': ['T1']} for name in ('success', 'empty', 'error')]
    return plan, module


class BehaviorContractTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def test_plan_without_the_gate_is_left_alone(self):
        f = self.f
        self.assertEqual(validate_plan(f.plan(), f.state()['modules']['M001']), digest(f.plan()))
        f.prepare()
        self.assertNotIn('scenario_index', f.state()['modules']['M001']['plan'])

    def test_new_rejections_point_to_the_relevant_small_protocol_section(self):
        import reading
        for reason, section in (('behavior_review required', '3. 分配与登记门禁'),
                                ('scenario_index is derived from the OpenSpec definitions', '冻结算法'),
                                ('required_test_ids must be unique', '逻辑单测')):
            self.assertEqual(reading.read_hint(reason)['section'], section)

    def test_three_scenarios_under_one_requirement_are_individually_frozen(self):
        plan, module = contract_plan(self.f)
        self.assertEqual(validate_plan(plan, module), digest(plan))
        for mutation, error in (
            (lambda p: p['scenario_trace'].pop(), 'every frozen Scenario'),
            (lambda p: p['paths'][-1].update(scenario_ids=['SCN-M001-empty']), 'omit scenario_ids'),
            (lambda p: p.update(scenario_index=[]), 'derived from the OpenSpec'),
            (lambda p: p['scenario_trace'][0].update(assertions=[{'path_id': 'P1', 'assertion_id': 'missing'}]), 'differ from the assertions that name it'),
            (lambda p: p['paths'][0]['expected_assertions'][0].pop('scenario_ids'), 'no assertion names scenario SCN-M001-success'),
            (lambda p: p['paths'][0]['expected_assertions'][0].update(scenario_ids=['SCN-M001-nowhere']), 'scenarios the SPEC does not define'),
            (lambda p: p['paths'][0]['expected_assertions'].append({'assertion_id': 'extra', 'expected': 1}), 'name no scenario'),
            (lambda p: p['source_closure'].update(unresolved=['source ambiguity']), 'unresolved'),
            (lambda p: p['source_closure'].pop('boundary_rationale'), 'boundary_rationale'),
            (lambda p: p['paths'][-1]['expected_assertions'][0].update(scenario_ids=['SCN-M001-success']), 'build/static'),
        ):
            broken = copy.deepcopy(plan); mutation(broken)
            with self.subTest(error=error), self.assertRaisesRegex(Rejected, error):
                validate_plan(broken, module)

    def test_the_trace_takes_its_assertions_from_the_assertions_that_name_the_scenario(self):
        f = self.f; plan, module = contract_plan(f)
        self.assertNotIn('assertions', plan['scenario_trace'][0])  # its author writes the tasks only
        completed = copy.deepcopy(plan); bc.complete(completed)
        self.assertEqual(completed['scenario_trace'][1], {'scenario_id': 'SCN-M001-empty', 'task_ids': ['T1'],
                                                          'assertions': [{'path_id': 'P1', 'assertion_id': 'empty'}]})
        self.assertEqual(validate_plan(completed, module), digest(completed))  # the completed trace stands as stored
        for row in plan['scenario_trace']:  # a row may still list them, as long as it lists exactly those
            row['assertions'] = [{'path_id': 'P1', 'assertion_id': row['scenario_id'].split('-')[-1]}]
        validate_plan(plan, module)

    def test_a_design_answers_to_its_spec_scenario_by_scenario(self):
        f = self.f; plan, _ = contract_plan(f)
        rows = bc.index(plan); paths = copy.deepcopy(plan['paths'])
        bc.check_design(rows, paths)
        for change, message in (
            (lambda p: p[0]['expected_assertions'][0].pop('scenario_ids'), 'needs scenario_ids'),
            (lambda p: p[0]['expected_assertions'][0].update(scenario_ids=['SCN-M001-nowhere']), 'does not define'),
            (lambda p: p[0]['expected_assertions'][0].update(scenario_ids=[]), 'needs scenario_ids'),
            (lambda p: p[0].update(requirement_id='R2'), 'another requirement'),
            (lambda p: p[0]['expected_assertions'].pop(), 'no design assertion verifies: SCN-M001-error'),
            (lambda p: p[-1]['expected_assertions'][0].update(scenario_ids=['SCN-M001-error']), 'build/static'),
        ):
            broken = copy.deepcopy(paths); change(broken)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                bc.check_design(rows, broken)

    def test_spec_edit_changes_the_derived_index_and_the_plan_hash(self):
        f = self.f; plan, module = contract_plan(f)
        before, index = validate_plan(plan, module), bc.index(plan)
        definition = next(r for r in plan['definitions'] if r['kind'] == 'spec')
        from pathlib import Path
        text = Path(definition['path']).read_text().replace('render error', 'preserve input and render error')
        definition.update(f.ref('contract-spec-changed.md', text))
        self.assertNotEqual(validate_plan(plan, module), before)  # a new hash needs a new freeze
        self.assertNotEqual(bc.index(plan), index)
        self.assertEqual([r['scenario_id'] for r in bc.index(plan)], [r['scenario_id'] for r in index])

    def test_duplicate_or_missing_scenario_id_is_rejected(self):
        f = self.f; plan, _ = contract_plan(f)
        definition = next(r for r in plan['definitions'] if r['kind'] == 'spec')
        from pathlib import Path
        original = Path(definition['path']).read_text()
        for text in (original.replace('SCN-M001-error', 'SCN-M001-empty'), original.replace('Scenario-ID: SCN-M001-error', '')):
            definition.update(f.ref('broken-spec.md', text))
            with self.assertRaisesRegex(Rejected, 'Scenario-ID|duplicate scenario_id'):
                bc.scenario_index(plan)

    def test_static_review_cannot_collapse_three_scenarios_to_one_requirement(self):
        f = self.f; plan, _ = contract_plan(f)
        code = f.target / 'code.py'; code.write_text('search = 1\n')
        entry = f.target / 'entry.py'; entry.write_text('from code import search\n')
        evidence = f.ref('review.md', 'Read production branch for each scenario')
        index = bc.index(plan)
        query = {**plan['paths'][-1], 'scenario_index': index, 'scenario_ids': [r['scenario_id'] for r in index], 'run_id': 'demo',
                 'module_id': 'M001', 'freeze_id': 'fz', 'code_baseline': 'cb'}
        data = {k: query[k] for k in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')}
        data.update(scenarios=[{'scenario_id': row['scenario_id'], 'requirement_id': 'R1', 'status': 'passed',
                               'summary': 'scenario reaches entry', 'production_symbols': [{'path': str(code), 'symbol': 'search'}],
                               'reached_from': {'path': str(entry), 'symbol': 'search'}, 'evidence_refs': [evidence]}
                              for row in index],
                    anti_patterns={p: {'status': 'absent', 'note': 'reviewed', 'evidence_refs': [evidence]}
                                   for p in spec_closure.ANTI_PATTERNS})
        self.assertEqual(spec_closure.report(query, f.ref('review.json', data), f.target)['quality'], 'green-passed')
        data['scenarios'][1].update(status='failed', summary='error branch missing')
        data['scenarios'][1]['production_symbols'] = []  # no implementation is an observed gap, not a report-format block
        failed = spec_closure.report(query, f.ref('failed-review.json', data), f.target)
        self.assertEqual(failed['quality'], 'red-bug')
        self.assertIn('SCN-M001-error', failed['root_cause']['summary'])
        data['scenarios'] = data['scenarios'][:1]
        with self.assertRaisesRegex(Rejected, 'cover exactly'):
            spec_closure.report(query, f.ref('partial-review.json', data), f.target)

    def test_shared_capability_requires_one_owner_and_real_consumers(self):
        f = self.f; _, m = contract_plan(f)
        m['behavior_review'] = review(f, m)
        sibling = copy.deepcopy(m); sibling['module_id'] = 'M002'
        shared = {'capability_id': 'provider', 'owner_module_id': 'M001', 'consumer_module_ids': ['M002'],
                  'integration_case_ids': ['C1'], 'integration_responsibility': 'M002 binds the real provider'}
        m['behavior_review']['shared_capabilities'] = [shared]
        sibling['behavior_review']['shared_capabilities'] = [dict(shared)]
        state = {'behavior_contract_required': True, 'modules': {'M001': m, 'M002': sibling}}
        bc.global_review(state)
        selected = {'source_id': 'TARGET', 'capability_id': 'provider', 'owner': 'M001'}
        bc.check_owners(state, [selected, {'source_id': 'TARGET', 'capability_id': 'unrelated', 'owner': None}])
        for owner in ('M002', None):  # the reuse catalogue may not name another owner for the same capability
            with self.assertRaisesRegex(Rejected, 'differs from the reuse catalogue'):
                bc.check_owners(state, [{**selected, 'owner': owner}])
        sibling['behavior_review']['shared_capabilities'][0]['owner_module_id'] = 'M002'
        with self.assertRaisesRegex(Rejected, 'competing owners'):
            bc.global_review(state)

    def test_runtime_review_ignores_unrelated_peer_but_checks_actual_dependency(self):
        import workflow
        f = self.f; _, m = contract_plan(f)
        m['behavior_review'] = review(f, m)
        peer = copy.deepcopy(m); peer['module_id'] = 'M002'
        peer['behavior_review']['evidence_refs'] = [f.ref('peer-review.md', 'separate peer review')]
        peer['behavior_review']['evidence_refs'][0]['sha256'] = '0' * 64
        state = {'behavior_contract_required': True, 'dimension_slicing_required': False,
                 'modules': {'M001': m, 'M002': peer}, 'module_groups': {}}
        self.assertEqual(workflow.runtime_allocations(state, 'M001'), {'M001'})
        m['dependencies'] = ['M002']
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            workflow.runtime_allocations(state, 'M001')

    def test_parent_shared_ownership_can_refine_to_one_child_writer(self):
        f = self.f; _, child = contract_plan(f)
        child['behavior_review'] = review(f, child)
        row = {'capability_id': 'query-provider', 'owner_module_id': 'M001', 'consumer_module_ids': ['M001'],
               'integration_case_ids': ['C1'], 'integration_responsibility': 'child wires query behavior'}
        child['behavior_review']['shared_capabilities'] = [row]
        parent = copy.deepcopy(child); parent.update(module_id='M010', children=['M001'])
        parent['behavior_review']['shared_capabilities'][0]['owner_module_id'] = 'M010'
        state = {'behavior_contract_required': True, 'modules': {'M001': child}, 'module_groups': {'M010': parent}}
        bc.global_review(state)
        parent['children'] = []
        with self.assertRaisesRegex(Rejected, 'outside parent allocation'):
            bc.global_review(state)

    def test_review_may_omit_its_allocation_but_cannot_contradict_it(self):
        _, module = contract_plan(self.f)
        lean = {k: v for k, v in review(self.f, module).items() if k not in COPIES}
        bc.review(module, lean)
        for field, wrong in (('scope_sha256', digest({'in': ['other']})), ('requirement_ids', ['R9']), ('case_ids', ['C9'])):
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, 'behavior review'):
                bc.review(module, {**lean, field: wrong})

    def test_shared_integration_case_belongs_to_consumer_not_duplicated_in_provider(self):
        f = self.f; _, provider = contract_plan(f)
        provider['behavior_review'] = review(f, provider)
        consumer = copy.deepcopy(provider); consumer.update(module_id='M002', case_ids=['C2'])
        consumer['behavior_review']['case_ids'] = ['C2']
        shared = {'capability_id': 'provider', 'owner_module_id': 'M001', 'consumer_module_ids': ['M002'],
                  'integration_case_ids': ['C2'], 'integration_responsibility': 'M002 tests real provider integration'}
        provider['behavior_review']['shared_capabilities'] = [shared]
        consumer['behavior_review']['shared_capabilities'] = [copy.deepcopy(shared)]
        state = {'behavior_contract_required': True, 'modules': {'M001': provider, 'M002': consumer}}
        bc.global_review(state)
        shared['integration_case_ids'] = ['UNASSIGNED']
        with self.assertRaisesRegex(Rejected, 'consumer owner'):
            bc.global_review(state)

    def test_parent_checks_children_reviews_and_rejection_does_not_mutate_siblings(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope()
        state = f.state(); state['behavior_contract_required'] = True
        parent = state['modules']['M010']
        plan = f.proposal()
        for child in plan['children']:
            child['behavior_review'] = review(f, child)
        decomposition.validate(state, parent, plan)
        before = copy.deepcopy(state)
        plan['children'][0]['behavior_review']['case_ids'] = []
        with self.assertRaisesRegex(Rejected, 'case_ids'):
            decomposition.validate(state, parent, plan)
        self.assertEqual(state, before)

    def test_registration_and_plan_gate_are_real_ledger_operations(self):
        f = self.f; old = f.state(); f.root = f.base / 'contract-run'
        payload = {k: old[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec', 'new_architecture')}
        f.call('init', {**payload, 'behavior_contract_required': True, 'dimension_slicing_required': False,
                       'context_readiness_required': False, 'split_testing_required': False}, role='host')
        module = {'module_id': 'M001', 'scope': {'in': ['query'], 'out': ['history'], 'requirement_ids': ['R1']},
                  'case_ids': ['C1'], 'write_paths': [str(f.target / 'm1')], 'context_refs': [f.ref('context.md', 'query sources')]}
        with self.assertRaisesRegex(Rejected, 'behavior_review'):
            f.call('register', module, role='global-orchestrator', module=None)
        module['behavior_review'] = {k: v for k, v in review(f, module).items() if k not in COPIES}
        f.call('register', module, role='global-orchestrator', module=None)
        f.global_plan()
        with self.assertRaisesRegex(Rejected, 'behavior review'):  # the run switches the contract on, for any plan
            f.call('plan', {'plan_ref': f.ref('bare-plan.json', f.plan())}, role='spec-designer')
        plan, _ = contract_plan(f)
        with self.assertRaisesRegex(Rejected, 'cannot opt out'):
            f.call('plan', {'plan_ref': f.ref('opt-out.json', {**plan, 'behavior_contract_required': False})}, role='spec-designer')
        del plan['behavior_contract_required']  # the author does not declare what the run already requires
        for key in COPIES:
            del plan['source_closure'][key]
        f.call('plan', {'plan_ref': f.ref('new-plan.json', plan)}, role='spec-designer')
        self.assertIs(f.state()['modules']['M001']['plan']['behavior_contract_required'], True)
        f.approve(f.state()['next_steps'][0]['approval_subject_sha256'], 'D-contract'); f.call('freeze', {'decision_id': 'D-contract'})
        self.assertEqual(len(f.state()['modules']['M001']['scenario_index']), 3)
        self.assertNotIn('scenario_index', f.state()['modules']['M001']['plan'])


if __name__ == '__main__':
    unittest.main()
