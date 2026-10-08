"""What a run settles once (where a user-visible case is verified, how the target takes resources) is asked before UI work
is registered, shown to a run already in flight, and carried to the project's next run."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import experience
import migration_report
import project_context as pc
import rule_debt
import user_paths
from contracts import Rejected, file_ref
import test_ledger
import test_project_context
import test_run_changes
import test_source_changes

NO_DEVICE = {'unavailable': 'this task has no device farm'}
DECLINED = {'declined': {'copy': 'the target bundles no files', 'parameters': 'values are typed in the design system'}}


class DeviceStatementTests(unittest.TestCase):
    def test_a_project_states_the_platforms_or_why_there_is_none(self):
        for device in ({'platforms': ['android']}, {'platforms': ['harmony', 'android']}, NO_DEVICE):
            self.assertEqual(pc.validate({'test_adapter': {'device': device}})['test_adapter']['device'], device)
        for bad in ({'platforms': []}, {'platforms': ['ios']}, {'platforms': ['android', 'android']}, {'unavailable': ' '},
                    {'platforms': ['android'], 'unavailable': 'both'}, {}, 'android'):
            with self.subTest(bad=bad), self.assertRaisesRegex(Rejected, r'test_adapter\.device'):
                pc.validate({'test_adapter': {'device': bad}})

    def test_the_statement_is_read_from_the_runs_current_context(self):
        self.assertIsNone(pc.device_verification({}))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / 'snapshot.json'
            path.write_text(json.dumps({'effective_config': {'test_adapter': {'device': NO_DEVICE}}}))
            self.assertEqual(pc.device_verification({'project_context_ref': file_ref(path)}), NO_DEVICE)
            path.write_text(json.dumps({'effective_config': {}}))
            self.assertIsNone(pc.device_verification({'project_context_ref': file_ref(path)}))


class RunLevelGapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()

    def ref(self, name, value):
        path = self.base / name
        path.write_text(json.dumps(value))
        return file_ref(path)

    def state(self, device):
        return {'project_context_ref': self.ref('snapshot.json', {'effective_config': {'test_adapter': {'device': device} if device else {}}})}

    def plan(self, *paths, **over):
        analysis = {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [{'item_id': 'SCREEN', 'case_ids': ['C1', 'C2', 'C3']}]}]}
        return {'dimension_analysis_ref': self.ref('analysis.json', analysis), 'paths': list(paths), **over}

    MODULE = {'module_id': 'M001', 'case_ids': ['C1', 'C2', 'C3', 'C4']}
    IN_PROCESS = [{'path_id': 'P' + c, 'case_id': c, 'kind': 'automation'} for c in ('C1', 'C2', 'C3', 'C4')]

    def test_with_no_device_stated_the_uncovered_cases_are_gaps_for_that_reason(self):
        state = self.state(NO_DEVICE)
        authored = {'case_id': 'C2', 'reason': 'the screen needs a paired second device', 'evidence_refs': [self.ref('gap.json', {})]}
        plan = user_paths.settle_gaps(state, self.MODULE, self.plan(*self.IN_PROCESS, {'path_id': 'V1', 'case_id': 'C1', 'kind': 'visual'},
                                                                     device_gaps=[authored]))
        gaps = user_paths.gaps(plan)
        self.assertEqual(sorted(gaps), ['C2', 'C3'])  # C1 has its visual path, C4 is not shown on a screen
        self.assertIs(gaps['C2'], authored)           # a reason the leaf gave stays its own
        self.assertEqual((gaps['C3']['reason'], gaps['C3']['evidence_refs']), (NO_DEVICE['unavailable'], [state['project_context_ref']]))
        user_paths.plan_gate(self.MODULE, plan)

    def test_with_platforms_stated_or_nothing_stated_the_leaf_still_owes_its_paths(self):
        for device in ({'platforms': ['android']}, None):
            plan = user_paths.settle_gaps(self.state(device), self.MODULE, self.plan(*self.IN_PROCESS))
            self.assertEqual(user_paths.gaps(plan), {})
            with self.assertRaisesRegex(Rejected, 'needs a device or visual path'):
                user_paths.plan_gate(self.MODULE, plan)

    def test_the_plan_operation_settles_gaps_only_in_a_prepared_run(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        with mock.patch.object(user_paths, 'settle_gaps', side_effect=lambda s, m, plan: plan) as settle:
            t.freeze('M001')
            self.assertEqual(settle.call_count, 1)
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        with mock.patch.object(user_paths, 'settle_gaps') as settle:
            f.prepare()
            settle.assert_not_called()


class VisibleToARunInFlightTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_run_changes.PreparedRunRevisionTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f

    def with_ui_leaf(self):
        """The run as it would be had a UI allocation been registered before anyone asked these questions."""
        state = self.f.state()
        analysis = self.t.source.d.analysis('M001', ('Logic', 'UI'))
        state['modules']['M001']['dimension_analysis_ref'] = self.f.ref('ui-leaf.json', analysis)
        return state

    def run_rows(self, state):
        return sorted(row['reason'].split(':')[0] for row in rule_debt.collect(state) if row['module_id'] == 'RUN')

    def test_what_nobody_settled_is_rule_debt_of_the_run(self):
        self.assertEqual(self.run_rows(self.f.state()), [])  # no UI or resource work: nothing to settle
        state = self.with_ui_leaf()
        self.assertEqual(self.run_rows(state), ['target_resources.copy is not settled', 'test_adapter.device is not settled'])
        state['target_resources'] = copy.deepcopy(DECLINED)
        with mock.patch.object(pc, 'device_verification', return_value=NO_DEVICE):
            self.assertEqual(self.run_rows(state), [])

    def test_a_held_plan_without_a_device_path_is_rule_debt_and_a_limitation_of_the_report(self):
        state = self.with_ui_leaf()
        m = state['modules']['M001']
        m['plan'] = {'dimension_analysis_ref': m['dimension_analysis_ref'], 'paths': [{'path_id': 'P1', 'case_id': 'C1', 'kind': 'automation'}]}
        debt = [row for row in rule_debt.collect(state) if row['module_id'] == 'M001' and 'device or visual path' in row['reason']]
        self.assertEqual([row['artifact'] for row in debt], ['plan'])
        _, limitations, _ = migration_report.fidelity(state, [], lambda ref: Path(ref['path']))
        row, = [x for x in limitations if x['kind'] == 'in-process-only']
        self.assertEqual((row['module_id'], row['case_ids']), ('M001', ['C1']))
        m['plan']['paths'].append({'path_id': 'V1', 'case_id': 'C1', 'kind': 'visual'})
        self.assertEqual([x for x in migration_report.fidelity(state, [], lambda ref: Path(ref['path']))[1] if x['kind'] == 'in-process-only'], [])

    def test_a_run_without_planning_coverage_gets_the_limitation_and_no_debt(self):
        state = self.with_ui_leaf(); state['planning_coverage_required'] = False
        m = state['modules']['M001']
        m['plan'] = {'dimension_analysis_ref': m['dimension_analysis_ref'], 'paths': [{'path_id': 'P1', 'case_id': 'C1', 'kind': 'automation'}]}
        self.assertEqual([row for row in rule_debt.collect(state) if row['module_id'] == 'RUN' or 'device or visual path' in row['reason']], [])
        self.assertEqual(len([x for x in migration_report.fidelity(state, [], lambda ref: Path(ref['path']))[1] if x['kind'] == 'in-process-only']), 1)


class CarriedToTheNextRunTests(unittest.TestCase):
    def test_a_harvest_keeps_what_the_run_settled(self):
        t = test_run_changes.PreparedRunRevisionTests(); t.setUp(); self.addCleanup(t.doCleanups)
        f = t.f
        report = t.report({'target_resources': DECLINED, 'test_adapter': {'device': NO_DEVICE}}, affected=())
        ref = f.ref('settle.json', report)
        receipt = f.ref('settle-context.json', f.report('global-planning', module=None, draft=ref))
        f.raw('run-review', {'report_ref': ref, 'context_ref': receipt}, role='global-orchestrator', module=None)
        f.call('revise-run', f.state()['global_next_step']['payload'], role='host', module=None)
        self.assertEqual(experience.settled(f.state()), {'target_resources': DECLINED, 'device': NO_DEVICE})
        project = t.source.config_root
        self.assertEqual(experience.conventions(project), {})
        experience.harvest(project, f.root)
        self.assertEqual(experience.conventions(project), {'target_resources': DECLINED, 'device': NO_DEVICE, 'run_id': 'demo'})

    def store(self, pj, facts):
        directory = experience.store(pj.root); directory.mkdir(parents=True, exist_ok=True)
        (directory / 'lessons.json').write_text(json.dumps({'schema_version': 1, 'runs': {}, 'conventions': {'demo': facts}}))

    def test_the_next_run_starts_from_it_where_the_project_is_silent(self):
        pj = test_project_context.ProjectContextTests(); pj.setUp(); self.addCleanup(pj.doCleanups)
        self.store(pj, {'target_resources': DECLINED, 'device': NO_DEVICE, 'run_id': 'earlier'})
        prepared = pj.prepare()
        config = pc.verify_snapshot(prepared['project_context_ref'])['effective_config']
        self.assertEqual((config['target_resources'], config['test_adapter']['device']), (DECLINED, NO_DEVICE))
        self.assertEqual(config['test_adapter']['executable'], pj.config['test_adapter']['executable'])  # the rest of the adapter is the project's
        self.assertEqual(prepared['input']['target_resources'], DECLINED)

    def test_what_the_project_states_itself_wins_and_a_convention_for_another_tree_is_not_taken(self):
        pj = test_project_context.ProjectContextTests(); pj.setUp(); self.addCleanup(pj.doCleanups)
        elsewhere = {'copy': {'root': '/another/target/res', 'path': '{kind}/{name}{ext}', 'accessor': 'Res.{kind}.{name}', 'formats': ['png']}}
        self.store(pj, {'target_resources': elsewhere, 'device': NO_DEVICE})
        pc.update(pj.root, pj.request('device', 1, {'test_adapter': {**pj.config['test_adapter'], 'device': {'platforms': ['android']}}}), pj.actor)
        config = pc.verify_snapshot(pj.prepare()['project_context_ref'])['effective_config']
        self.assertEqual(config['test_adapter']['device'], {'platforms': ['android']})
        self.assertFalse(config.get('target_resources'))


if __name__ == '__main__':
    unittest.main()
