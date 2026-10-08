"""An accepted artifact keeps the contract it was accepted under; afterwards only drift can refuse it.

Each test accepts something under today's rules, then stands in for "a rule written later" by making one content
check refuse everything, and shows that the accepted artifact is still read, a new artifact still answers to the
rule, and the difference is reported instead of blocking the run.
"""
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import design_stage
import dimensions
import migration_report
import resource_fidelity
import rule_debt
import semantics
import telemetry
import test_design_stage
import test_dimensions
import test_ledger
import workflow
from contracts import Drifted, Rejected, digest, intact

LATER = Rejected('a rule written after this was accepted')


def debts(state):
    return {(row['module_id'], row['artifact']) for row in rule_debt.collect(state)}


class IntactTests(unittest.TestCase):
    def test_only_drift_refuses_what_was_accepted(self):
        def fail(error):
            raise error
        self.assertEqual(intact(lambda: 'read'), 'read')
        for error in (Rejected('a later rule'), KeyError('a field a later rule requires'), TypeError('a later shape')):
            self.assertIsNone(intact(lambda: fail(error)))
        with self.assertRaises(Drifted):
            intact(lambda: fail(Drifted('a cited file changed')))


class Leaves(unittest.TestCase):
    """A root split into two leaves with registered analyses, before any leaf plan."""
    def setUp(self):
        self.d = test_dimensions.DimensionTests(); self.d.setUp(); self.addCleanup(self.d.doCleanups)
        self.f = self.d.f
        self.d.root(); self.f.split(self.d.proposal(ids=('M001', 'M002'))); self.f.global_plan()

    def approve(self, did='D'):
        f = self.f
        f.call('decision', {'decision_id': did, 'decision': 'approved', 'module_id': 'M001',
                            'subject_sha256': f.state()['modules']['M001']['plan_hash'],
                            'human_source_ref': f.ref(did + '.md', 'approve')}, role='host', module=None)


class RegisteredAllocationTests(Leaves):
    def test_a_later_rule_does_not_refuse_a_registered_allocation_and_is_reported(self):
        f = self.f
        self.assertNotIn(('M001', 'allocation'), debts(f.state()))
        with mock.patch.object(semantics, 'validate_items', side_effect=LATER):
            workflow.runtime_allocations(f.state(), 'M001')  # a dispatch reads it
            f.call('plan', {'plan_ref': f.ref('plan.json', self.d.leaf_plan())}, role='spec-designer')  # so does planning
            with self.assertRaisesRegex(Rejected, 'written after'):
                dimensions.judge(f.state()['modules']['M001']['dimension_analysis_ref'], 'M001')  # a proposal answers to it
            rows = rule_debt.collect(f.state())
        self.assertIn(('M001', 'allocation'), {(row['module_id'], row['artifact']) for row in rows})
        self.assertTrue(all('written after' in row['reason'] for row in rows if row['artifact'] == 'allocation'))

    def test_drift_of_what_a_registered_allocation_cites_still_refuses_it(self):
        workflow.runtime_allocations(self.f.state(), 'M001')
        (self.f.base / 'dimension-source.md').write_text('changed after the allocation was registered')
        with self.assertRaises(Drifted):
            workflow.runtime_allocations(self.f.state(), 'M001')

    def test_a_resplit_reads_the_child_it_restates_and_judges_the_child_it_changes(self):
        f, d = self.f, self.d
        with mock.patch.object(semantics, 'validate_items', side_effect=LATER):
            f.call('redecompose', {'plan_ref': f.ref('same-split.json', d.proposal(ids=('M001', 'M002')))}, module='M010')
            changed = d.proposal(ids=('M001', 'M002'))
            analysis = d.analysis('M001', ('Logic',), d.root_ref)
            analysis['dimensions'][1]['items'][0]['behavior'] = 'a restated behavior'
            changed['children'][0]['dimension_analysis_ref'] = f.ref('M001-dimensions-restated.json', analysis)
            with self.assertRaisesRegex(Rejected, 'written after'):
                f.call('redecompose', {'plan_ref': f.ref('changed-split.json', changed)}, module='M010')

    def test_the_report_lists_rule_debt_for_the_auditor(self):
        f = self.f
        self.assertNotIn('## 规则欠账', migration_report.render(migration_report.build(f.root, f.state(), 1)))
        with mock.patch.object(semantics, 'validate_items', side_effect=LATER):
            report = migration_report.build(f.root, f.state(), 1)
        self.assertIn({'module_id': 'M002', 'artifact': 'allocation', 'reason': 'a rule written after this was accepted'}, report['rule_debt'])
        self.assertIn('## 规则欠账', migration_report.render(report))


class RegisteredPlanTests(Leaves):
    def test_a_later_rule_does_not_refuse_the_plan_the_ledger_holds(self):
        f = self.f
        plan = self.d.leaf_plan(); ref = f.ref('plan.json', plan)
        f.call('plan', {'plan_ref': ref}, role='spec-designer')
        held = f.state()['modules']['M001']['plan_hash']
        with mock.patch.object(telemetry, 'validate', side_effect=LATER):
            f.call('plan', {'plan_ref': ref}, role='spec-designer')  # the same plan, submitted again: read
            self.assertEqual(f.state()['modules']['M001']['plan_hash'], held)
            other = copy.deepcopy(plan); other['tasks'][0]['description'] = 'another plan'
            with self.assertRaisesRegex(Rejected, 'written after'):
                f.call('plan', {'plan_ref': f.ref('other-plan.json', other)}, role='spec-designer')  # a new plan answers to it
            self.approve(); f.call('freeze', {'decision_id': 'D'})  # freezing does not judge the plan again
            self.assertIn(('M001', 'plan'), debts(f.state()))
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')

    def test_what_concerns_the_allocation_alone_is_judged_when_the_leaf_is_first_frozen(self):
        f = self.f
        plan = self.d.leaf_plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer'); self.approve()
        with mock.patch.object(resource_fidelity, 'allocation_gate', side_effect=LATER):
            with self.assertRaisesRegex(Rejected, 'written after'):
                f.call('freeze', {'decision_id': 'D'})  # never frozen on this allocation: it is judged now
        f.call('freeze', {'decision_id': 'D'})
        for number, error in ((2, LATER), (3, Drifted('a file the allocation cites changed'))):
            revised = copy.deepcopy(plan); revised['tasks'][0]['description'] = 'refined guidance %d' % number
            impact = f.ref('impact-%d.json' % number, {'from_freeze_id': f.state()['modules']['M001']['freeze_id'],
                                                         'to_plan_hash': digest(revised), 'summary': 'no semantic change'})
            f.call('change', {'request_ref': f.ref('cr-%d.md' % number, 'refine'), 'impact_ref': impact})
            f.call('plan', {'plan_ref': f.ref('plan-%d.json' % number, revised)}, role='spec-designer')
            with mock.patch.object(resource_fidelity, 'allocation_gate', side_effect=error):
                if isinstance(error, Drifted):
                    with self.assertRaises(Drifted):  # drift is still refused
                        f.call('freeze', {'change_class': 'within-envelope', 'impact_ref': impact})
                else:  # frozen on this allocation before: a later rule about it is not applied again
                    f.call('freeze', {'change_class': 'within-envelope', 'impact_ref': impact})
                    self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')


class AcceptedDesignTests(unittest.TestCase):
    def flow(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups); f.global_plan()
        return f

    def test_a_later_rule_does_not_refuse_an_accepted_design_but_a_new_design_answers_to_it(self):
        f = self.flow()
        plan = test_design_stage.prepare_design(f, f.plan())
        with mock.patch.object(design_stage, 'check_assets', side_effect=LATER):
            state = f.state()
            self.assertTrue(design_stage.ready(state, state['modules']['M001']))
            f.call('plan', {'plan_ref': f.ref('accepted-plan.json', plan)}, role='spec-designer')
            f.approve(f.state()['modules']['M001']['plan_hash'], 'D'); f.call('freeze', {'decision_id': 'D'})
            self.assertIn(('M001', 'test-design'), debts(f.state()))
            g = self.flow()
            a, result = test_design_stage.start_design(g, g.plan())
            with self.assertRaisesRegex(Rejected, 'written after'):
                test_design_stage.submit_design(g, a, result)
        self.assertEqual(f.state()['modules']['M001']['phase'], 'frozen')

    def test_a_stale_input_still_refuses_an_accepted_design(self):
        f = self.flow()
        test_design_stage.prepare_design(f, f.plan())
        state = f.state(); m = state['modules']['M001']
        m['design_generation'] = m.get('design_generation', 0) + 1  # the allocation or context moved on
        with self.assertRaisesRegex(Rejected, 'design input stale'):
            design_stage.accepted(state, m)


if __name__ == '__main__':
    unittest.main()
