"""Fact-triggered reading, API closure and runtime parameters, including actual Ledger freeze gates."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import api_contract
import dimensions
import parameter_file
import reading
import test_dimensions
import test_parameter_file
from contracts import Rejected, check_ref, digest, file_ref


class ProgressiveReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def ref(self, data):
        path = self.root / 'analysis.json'; path.write_text(json.dumps(data))
        return file_ref(path)

    def test_global_auditor_and_runner_activate_only_the_applicable_topics(self):
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': []}]}
        m = {'dimension_analysis_ref': self.ref(analysis)}
        s = {'modules': {'M001': m}}
        auditor = reading.card(s, None, {'role': 'auditor', 'operation': 'audit-code-review'})
        self.assertTrue(any(row['ref'].endswith('ui-fidelity.md') for row in auditor))
        self.assertFalse(any(row['ref'].endswith('resource-transfer.md') for row in auditor))
        build = reading.card(s, None, {'role': 'test-runner', 'operation': 'audit-test-assign', 'test_scope': 'build'})
        self.assertFalse(any(row['ref'].endswith('ui-fidelity.md') for row in build))
        omitted = reading.card(s, None, {'role': 'auditor', 'operation': 'audit', 'module_ids': ['M002']})
        self.assertFalse(any(row['ref'].endswith('ui-fidelity.md') for row in omitted))

    def test_api_topic_is_loaded_without_ui_and_incremental_card_tracks_content_changes(self):
        m = {'dimension_analysis_ref': self.ref({'api_inventory_ref': {'path': 'bound-by-dispatch-gate'}, 'dimensions': []})}
        rows = reading.card({}, m, {'role': 'implementer', 'operation': 'assign'})
        self.assertIn((reading.P + 'resource-transfer.md', 'API 与 URL 契约'), [(r['ref'], r['section']) for r in rows])
        held = reading.delivered(rows)
        self.assertEqual([row['ref'] for row in reading.fresh(rows, held)], ['AGENTS.md'])  # the red lines are on every card
        changed = copy.deepcopy(rows); changed[-1]['sha256'] = 'new-content'
        self.assertEqual(reading.fresh(changed, held)[1:], [changed[-1]])
        self.assertIn('template/api-inventory.json', reading.templates({}, m, {'role': 'spec-designer', 'operation': 'plan'}))

    def test_all_fact_triggers_fit_the_card_and_template_budgets(self):
        m = {'plan': {'dimension_analysis_ref': self.ref({'api_inventory_ref': {'path': 'bound'}, 'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'parameter_sheet_ref': {'path': 'bound'},
             'items': [{'source_resource': 'image'}]},
            {'dimension': 'Resource', 'status': 'applicable', 'copy_plan_ref': {'path': 'bound'}, 'items': []}]}),
            'telemetry': {'status': 'applicable'}}}
        s = {'reuse_required': True, 'dependency_resolution_required': True}
        for role, op, scope, mode in itertools.product(reading.ROLE,
                (None, 'plan', 'assign', 'freeze', 'decompose', 'register', 'source-review'),
                (None, 'build', 'automation', 'visual'), (None, 'design')):
            step = {'role': role, 'operation': op, 'test_scope': scope, 'mode': mode}
            with self.subTest(step=step):
                self.assertLessEqual(sum(row['bytes'] for row in reading.card(s, m, step)), reading.READ_BUDGET)
                self.assertLessEqual(sum((reading.PACKAGE / n).stat().st_size for n in reading.templates(s, m, step)),
                                     reading.TRIGGERED_TEMPLATE_BUDGET)


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = self.f = d.f
        self.fixture = f.ref('api-fixture.json', {'query': 'fixed', 'result': ['one'], 'unauthorized': 'error'})
        self.source = {'api_id': 'QUERY', 'source_ref': f.ref('api-source.kt', 'fun query(q: String) = GET("/query", q)'),
            'source_symbol': 'query', 'method': 'GET', 'url': '/query', 'request_fields': ['q'],
            'response_fields': ['items'], 'error_outcomes': ['unauthorized'], 'state_effects': ['content']}
        self.contract = {'api_id': 'QUERY', 'fidelity': 'exact', 'fixture_contract_ref': self.fixture,
            'target': {'method': 'GET', 'url': '/query', 'consumer': str(f.target / 'm1/api.py') + '#query',
                'request_mapping': {'q': 'q'}, 'response_mapping': {'items': 'items'},
                'error_mapping': {'unauthorized': 'error'}, 'state_mapping': {'content': 'content'}}}
        self.items = {'D': {'dimension': 'Logic', 'api_ids': ['QUERY']}}

    def analysis(self, contract=None):
        return {'module_id': 'M001', 'api_inventory_ref': self.f.ref('api-inventory.json', {
            'schema_version': 1, 'module_id': 'M001', 'calls': [self.source],
            'contracts': [contract or self.contract], 'exclusions': []})}

    def plan(self):
        return {'paths': [{'path_id': 'P1', 'kind': 'automation', 'fixture_contract_ref': self.fixture}],
            'dimension_trace': [{'item_id': 'D', 'assertions': [{'path_id': 'P1', 'assertion_id': 'A1',
                'api_obligations': sorted(api_contract.obligations('QUERY', self.source))}]}],
            'decision_envelope': {'allowed_alternatives': []}}

    def test_missing_route_field_error_state_or_owner_is_rejected(self):
        for field in ('request_mapping', 'response_mapping', 'error_mapping', 'state_mapping'):
            contract = copy.deepcopy(self.contract); contract['target'][field] = {}
            with self.subTest(field=field), self.assertRaisesRegex(Rejected, 'omits a source obligation'):
                api_contract.load(self.analysis(contract), self.items)
        contract = copy.deepcopy(self.contract); contract['target']['url'] = '/other'
        with self.assertRaisesRegex(Rejected, 'exact method/URL changed'): api_contract.load(self.analysis(contract), self.items)
        with self.assertRaisesRegex(Rejected, 'ownership'): api_contract.load(self.analysis(), {})

    def test_api_requires_frozen_fixture_and_every_behavior_obligation(self):
        analysis, plan = self.analysis(), self.plan()
        api_contract.plan(analysis, self.items, plan)
        plan['dimension_trace'][0]['assertions'][0]['api_obligations'].remove('QUERY/error_outcomes:unauthorized')
        with self.assertRaisesRegex(Rejected, 'coverage incomplete'): api_contract.plan(analysis, self.items, plan)
        plan = self.plan(); plan['paths'][0]['kind'] = 'build'
        with self.assertRaisesRegex(Rejected, 'actual behavior'): api_contract.plan(analysis, self.items, plan)
        plan = self.plan(); plan['paths'][0]['fixture_contract_ref'] = self.f.ref('wrong-fixture.md', 'Different input')
        with self.assertRaisesRegex(Rejected, 'frozen fixture'): api_contract.plan(analysis, self.items, plan)

    def test_scope_exclusion_does_not_excuse_missing_or_changed_source_evidence(self):
        def excluded(source):
            return {'module_id': 'M001', 'api_inventory_ref': self.f.ref('excluded-api.json', {
                'schema_version': 1, 'module_id': 'M001', 'calls': [source], 'contracts': [],
                'exclusions': [{'api_id': 'QUERY', 'reason': 'Outside this migration scope', 'evidence_refs': [self.fixture]}]})}
        api_contract.load(excluded(self.source), {})
        invalid = copy.deepcopy(self.source); invalid['source_ref']['sha256'] = '0' * 64
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): api_contract.load(excluded(invalid), {})
        invalid = copy.deepcopy(self.source); invalid.pop('error_outcomes')
        with self.assertRaisesRegex(Rejected, 'source facet'): api_contract.load(excluded(invalid), {})

    def test_adaptation_cannot_freeze_using_only_a_technical_review(self):
        contract = copy.deepcopy(self.contract); contract.update(fidelity='approved-adaptation', alternative='new-endpoint', reason='Approved route change')
        contract['target']['url'] = '/v2/query'
        analysis = self.analysis(contract); plan = self.plan()
        plan['decision_envelope']['allowed_alternatives'] = ['new-endpoint']
        api_contract.plan(analysis, self.items, plan)
        # freeze loads the actual dimension schema, preserving the normal semantic-model checks.
        complete = self.d.analysis('M001'); complete['api_inventory_ref'] = analysis['api_inventory_ref']
        complete['api_review'].update(status='applicable', discovery_refs=[self.source['source_ref']])
        next(row for row in complete['dimensions'] if row['dimension'] == 'Logic')['items'][0]['api_ids'] = ['QUERY']
        module = {'module_id': 'M001', 'plan': {'dimension_analysis_ref': self.f.ref('api-adaptation-dimensions.json', complete)}, 'plan_hash': 'frozen-plan'}
        state = {'decisions': {}}
        with self.assertRaisesRegex(Rejected, 'exact Human decision'): api_contract.freeze(state, module, {'review_ref': self.fixture})
        state['decisions']['D'] = {'module_id': 'M001', 'subject_sha256': 'old-plan', 'consumed': False}
        with self.assertRaisesRegex(Rejected, 'exact Human decision'): api_contract.freeze(state, module, {'decision_id': 'D'})
        state['decisions']['D']['subject_sha256'] = 'frozen-plan'
        api_contract.freeze(state, module, {'decision_id': 'D'})
        state['decisions']['D']['consumed'] = True
        with self.assertRaisesRegex(Rejected, 'exact Human decision'): api_contract.freeze(state, module, {'decision_id': 'D'})

    def test_declared_consumer_is_hash_checked_and_is_an_actual_submitted_production_file(self):
        analysis = self.analysis()
        code = self.f.ref('target/m1/api.py', 'def query(q): return {"items": [q]}')
        result = {'code_files': [code], 'dimension_evidence': [{'item_id': 'D', 'consumer_refs': [code]}]}
        api_contract.implementation(analysis, self.items, result)
        result['dimension_evidence'][0]['consumer_refs'] = []
        with self.assertRaisesRegex(Rejected, 'production consumer'): api_contract.implementation(analysis, self.items, result)

    def test_actual_ledger_plan_and_freeze_require_api_assertion_coverage(self):
        d, f = self.d, self.f; original = d.analysis
        def analysis(*args, **kwargs):
            data = original(*args, **kwargs); mid = data['module_id']
            data['api_review'].update(status='applicable', discovery_refs=[self.source['source_ref']])
            data['api_inventory_ref'] = f.ref('inventory-'+mid+'.json', {'schema_version': 1, 'module_id': mid,
                'calls': [self.source], 'contracts': [self.contract], 'exclusions': []})
            next(row for row in data['dimensions'] if row['dimension'] == 'Logic')['items'][0]['api_ids'] = ['QUERY']
            return data
        d.analysis = analysis
        d.root(); f.split(d.proposal()); f.global_plan()
        plan = d.leaf_plan(); plan['paths'][0]['fixture_contract_ref'] = self.fixture
        with self.assertRaisesRegex(Rejected, 'coverage incomplete'):
            f.call('plan', {'plan_ref': f.ref('missing-api-plan.json', plan)}, role='spec-designer')
        plan['dimension_trace'][0]['assertions'][0]['api_obligations'] = sorted(api_contract.obligations('QUERY', self.source))
        f.call('plan', {'plan_ref': f.ref('complete-api-plan.json', plan)}, role='spec-designer')
        f.call('decision', {'decision_id': 'API-APPROVAL', 'decision': 'approved', 'module_id': 'M001',
            'subject_sha256': f.state()['modules']['M001']['plan_hash'],
            'human_source_ref': f.ref('approval.md', 'Fixture approval of this exact plan')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'API-APPROVAL'})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')


class DynamicParameterTests(test_parameter_file.ParameterFileTests):
    def runtime_fill(self):
        analysis = self.analysis(); params = parameter_file.ui_parameters.parameters(analysis)
        p = next(p for p in params if p['id'] == 'code:Home/title.alpha')
        fill = copy.deepcopy(self.fill); fill.pop('settled')
        fill['runtime'] = [{'id': p['id'], 'source_expression': p['text'], 'inputs': ['visible'],
            'consumer': str(self.target / 'screen.kt') + '#alphaFor', 'reason': 'Preserve both visibility states',
            'evidence_refs': [file_ref(next(Path(self.args.android_root).rglob('Home.kt')))], 'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}]}]
        return fill

    def test_dynamic_expression_is_not_generated_as_a_constant_and_needs_its_consumer(self):
        fill = self.runtime_fill(); analysis = self.analysis(fill)
        rows = self.decided(fill)
        self.assertEqual(rows['code:Home/title.alpha']['status'], 'runtime')
        document = parameter_file.ui_parameters.load(analysis)
        files, accessors = parameter_file.render(document, fill)
        self.assertNotIn(parameter_file.ui_parameters.key('code:Home/title.alpha'), ''.join(files.values()))
        for path, text in files.items():
            target = Path(path); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
        consumer = self.target / 'screen.kt'; consumer.write_text('fun alphaFor(visible: Boolean) = if (visible) 1f else 0f\n' + '\n'.join(accessors))
        parameter_file.verify(analysis, [file_ref(consumer)])
        consumer.write_text('\n'.join(accessors))
        with self.assertRaisesRegex(Rejected, 'runtime/layout binding'): parameter_file.verify(analysis, [file_ref(consumer)])

    def test_dynamic_and_structural_bindings_require_real_behavior_assertions(self):
        fill = self.runtime_fill(); analysis = self.analysis(fill)
        with self.assertRaisesRegex(Rejected, 'frozen behavioral assertion'):
            parameter_file.gate(self.state(), {'paths': [], 'decision_envelope': {}}, analysis)
        plan = {'paths': [{'path_id': 'P1', 'kind': 'unit', 'expected_assertions': [{'assertion_id': 'A1', 'expected': True}]}], 'decision_envelope': {}}
        fill['not_applicable'] = [{'ids': [p['id'] for p in parameter_file.ui_parameters.parameters(analysis) if p['class'] == 'keyword'],
            'reason': 'This fixture isolates the runtime alpha binding'}]
        parameter_file.gate(self.state(), plan, self.analysis(fill))
        fill['runtime'][0]['source_expression'] = '1f'
        with self.assertRaisesRegex(Rejected, 'differs from recorded'): self.decided(fill)

    def test_constant_requires_source_proof(self):
        self.fill['settled'][0].pop('constant_evidence_refs')
        with self.assertRaisesRegex(Rejected, 'constant without source proof'):
            self.gate()

    def test_structural_layout_mapping_and_runtime_mapping_are_both_required(self):
        fill = self.runtime_fill(); analysis = self.analysis(fill)
        plan = {'paths': [{'path_id': 'P1', 'kind': 'unit', 'expected_assertions': [{'assertion_id': 'A1', 'expected': True}]}], 'decision_envelope': {}}
        with self.assertRaisesRegex(Rejected, 'layout keywords'):
            parameter_file.gate(self.state(), plan, analysis)
        source = next(row for row in analysis['dimensions'] if row['dimension'] == 'UI')['parameter_sheet_ref']
        fill['structural'] = [{'id': p['id'], 'source_expression': p.get('text', p.get('value')),
            'consumer': str(self.target / 'screen.kt') + '#layoutContract', 'reason': 'Preserve constraints and zero spacing',
            'evidence_refs': [source], 'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}]}
            for p in parameter_file.ui_parameters.parameters(analysis) if p['class'] == 'keyword']
        parameter_file.gate(self.state(), plan, self.analysis(fill))
