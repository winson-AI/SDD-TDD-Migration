"""Completeness is owed, consistency is refused: inside a leaf's request each of these gates records the gap and the
first version goes on; outside one (a rehearsal, a tool, a direct call) the same check still refuses."""
import copy
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, carrying, validate_plan
import data_contract
import dimensions
import prepared_tests
import test_validation as tv
import test_behavior_contract
import test_data_contract
import test_dimensions
import test_evidence_handoff
import test_image_plan
import test_iterative_spec
import test_ledger
import test_parameter_file
import test_resource_signal_closure
import test_spec_closure
import test_telemetry
import test_ui_fidelity


class OwedGateTests(unittest.TestCase):
    def fixture(self, cls, *args):
        t = cls(*args); t.setUp(); self.addCleanup(t.doCleanups); return t

    def owed(self, message, call):
        with self.assertRaisesRegex(Rejected, message):  # a direct call refuses
            call()
        with carrying() as gaps:  # a leaf's request goes on and owes it
            call()
        self.assertTrue(any(message in gap for gap in gaps), gaps)
        return gaps

    def test_a_resource_reference_without_its_item_is_owed(self):
        t = self.fixture(test_resource_signal_closure.SignalClosureTests)
        t.nested_selector()
        self.owed('resource closure reduced; uncovered presentation refs: @drawable/ic_off', t.s.freeze)
        t.cover_files(); t.s.freeze()

    def test_an_image_source_without_its_item_is_owed(self):
        t = self.fixture(test_resource_signal_closure.SignalClosureTests)
        t.loader(); signal = t.signal(); t.cover_files()
        self.owed('UI image source closure requires one item for ' + signal['id'], t.s.freeze)

    def test_a_missing_source_closure_facet_is_owed(self):
        t = self.fixture(test_ui_fidelity.UiFidelityTests)
        module, _ = t.strict_module()
        module['plan']['source_closure'].pop('ui_renderers')
        self.owed('source_closure.ui_renderers must name the renderers', lambda: t.strict_freeze(module))
        module, _ = t.strict_module()
        module['plan']['source_closure'].pop('states')
        self.owed('source_closure.states required for UI scope', lambda: t.strict_freeze(module))

    def test_a_runtime_target_without_its_visual_path_and_a_picture_without_its_check_are_owed(self):
        t = self.fixture(test_image_plan.ImagePlanTests)
        t.declare(t.check)
        module = t.f.module(); module['plan']['paths'] = [t.asset_path()]
        import ui_fidelity
        self.owed('runtime UI targets lack visual paths: ' + t.coverage, lambda: ui_fidelity.baseline_gate(t.f.state, module))
        t.f.model.pop('image_check_waivers')
        self.owed('need an image check or a waiver with evidence', t.gate)

    def test_an_untraced_scenario_and_an_unassigned_assertion_are_owed(self):
        f = self.fixture(test_ledger.FlowTests)
        plan, module = test_behavior_contract.contract_plan(f)
        validate_plan(plan, module)
        short = copy.deepcopy(plan); short['scenario_trace'].pop()
        gaps = self.owed('scenario_trace must cover every frozen Scenario', lambda: validate_plan(short, module))
        self.assertTrue(any(gap.startswith('behavior assertions name no scenario') for gap in gaps), gaps)
        bare = copy.deepcopy(plan); bare['paths'][0]['expected_assertions'][0].pop('scenario_ids')
        self.owed('no assertion names scenario SCN-M001-success', lambda: validate_plan(bare, module))
        unknown = copy.deepcopy(plan); unknown['scenario_trace'].append({'scenario_id': 'SCN-M001-nowhere', 'task_ids': ['T1']})
        with carrying(), self.assertRaisesRegex(Rejected, 'names a scenario the SPEC does not define'):  # a contradiction is not owed
            validate_plan(unknown, module)
        without_static = copy.deepcopy(plan); without_static['paths'] = [p for p in plan['paths'] if p['kind'] != 'static']
        without_static['tasks'][0]['path_ids'] = [p for p in without_static['tasks'][0]['path_ids'] if p != 'S1']
        self.owed('scenario contract requires one static review PATH', lambda: validate_plan(without_static, module))

    def test_a_dimension_trace_that_stops_at_the_build_is_owed(self):
        d = self.fixture(test_dimensions.DimensionTests); f = d.f
        d.root(('Logic', 'Resource')); f.split(d.proposal(('Logic', 'Resource')))
        plan = d.leaf_plan(); module = f.state()['modules']['M001']
        dimensions.validate_plan(plan, module)
        plan['paths'][0]['kind'] = 'build'
        self.owed('dimension behavior requires case paths; build alone is not fidelity', lambda: dimensions.validate_plan(plan, module))

    def test_a_data_obligation_without_a_behavior_test_is_owed(self):
        t = self.fixture(test_data_contract.DataContractTests)
        analysis, plan = t.analysis(), t.plan()
        plan['paths'][0]['kind'] = 'build'
        gaps = self.owed('data fidelity requires actual behavior tests', lambda: data_contract.plan(analysis, t.items, plan))
        self.assertTrue(any(gap.startswith('data behavior assertion coverage incomplete') for gap in gaps), gaps)

    def test_a_deferred_preparation_is_owed_at_freeze(self):
        f = self.fixture(test_ledger.FlowTests); f.global_plan()
        design = test_iterative_spec.direct_plan(f, f.plan())
        design['paths'][0]['preparation'] = {'status': 'deferred', 'reason': 'Fixture absent', 'asset_ids': [], 'evidence_refs': [design['design_ref']],
                                             'owner': 'MO', 'next_action': 'Prepare approved fixture'}
        self.owed('resolve deferred test preparation before freeze', lambda: prepared_tests.preparation(design, required=True, freezing=True))

    def test_an_unsettled_expression_and_an_unmapped_token_are_owed(self):
        t = self.fixture(test_parameter_file.ParameterFileTests)
        self.owed('expressions the Spec must settle or mark not applicable', lambda: t.gate(t.analysis({'tokens': t.fill['tokens']})))
        self.owed('tokens the Spec must map or mark not applicable', lambda: t.gate(t.analysis({'settled': t.fill['settled']})))

    def test_a_task_without_its_telemetry_review_is_owed(self):
        t = self.fixture(test_telemetry.TelemetryTests); f = t.f
        plan = t.plan(True); module = f.state()['modules']['M001']
        validate_plan(plan, module)
        plan['tasks'].append({'task_id': 'T2', 'requirement_ids': ['R1'], 'path_ids': ['P1']})  # a task nobody has reviewed for telemetry
        for d in plan['definitions']:
            if d['kind'] == 'tasks':
                d.update(f.ref('tasks-two.md', '- [ ] T1 event\n- [ ] T2 plain formatting\n'))
        self.owed('telemetry review must cover scoped tasks', lambda: validate_plan(plan, module))
        plan = t.plan(True); plan['telemetry']['tasks'].append({'task_id': 'T9', 'status': 'not-applicable', 'reason': 'no such task', 'event_ids': []})
        with carrying(), self.assertRaisesRegex(Rejected, 'names a task outside the plan'):
            validate_plan(plan, module)

    def test_a_missing_static_path_is_owed_and_a_second_one_is_refused(self):
        t = self.fixture(test_spec_closure.SpecClosureTests); f = t.f
        plan = f.plan()
        missing = copy.deepcopy(plan); missing['paths'] = [p for p in missing['paths'] if p['kind'] != 'static']
        self.owed('spec_closure_required: plan one static spec-closure PATH', lambda: tv.plan_check(missing, str(f.target), static_required=True))
        twice = copy.deepcopy(plan); twice['paths'].append({**next(p for p in plan['paths'] if p['kind'] == 'static'), 'path_id': 'S2'})
        with carrying(), self.assertRaisesRegex(Rejected, 'one static PATH, not several'):
            tv.plan_check(twice, str(f.target), static_required=True)


if __name__ == '__main__':
    unittest.main()
