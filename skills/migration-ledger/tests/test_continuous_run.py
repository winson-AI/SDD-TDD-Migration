"""A run walked by its cursor from the root's registration to the audit verdict, with no fixture step in between: the
Ledger writes the coverage the registration states and drafts the split, the orchestrator confirms the cut, both leaves are
planned, coded and tested, and the unified audit gives the verdict. Every step the cursor marks mechanical is left to
`ledger.py advance`; every other one is a model's turn, scripted here and counted. The counts are reported, not a gate."""
import json
from pathlib import Path
import sys
import unittest
import warnings

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import behavior_contract
import split_draft
import test_run_rehearsal
import test_source_changes
import workflow_cost
from contracts import read_json

FEATURES = [{'feature_id': fid, 'name': name, 'functional_path': 'Search/' + name, 'trigger': 'open ' + name, 'observable_result': name + ' shown',
             'requirement_ids': ['R1'], 'case_ids': cases, 'evidence_refs': []}
            for fid, name, cases in (('F-QUERY', 'Query', ['C1', 'C2', 'C3']), ('F-HISTORY', 'History', ['C4', 'C5', 'C6']))]
# The counts last recorded in VERIFICATION.md: model turns by role, and the most protocol bytes one turn's card handed a model.
RECORDED = {'turns': {'global-orchestrator': 1, 'module-orchestrator': 1, 'spec-designer': 2, 'implementer': 2, 'test-runner': 2, 'auditor': 1},
            'card_bytes': 19795}


class ContinuousWalk(test_run_rehearsal.RunWalk):
    """A run whose root has two features of three cases each, registered and nothing else."""
    features = FEATURES

    def setUp(self):
        self.t = test_source_changes.SourceChangeTests(methodName='runTest'); self.f = self.t.register_root(self.features)
        self.plan_of_one_case, self.t.plan = self.t.plan, self.leaf_plan
        self.setup_turns = [{'role': e['actor']['role'], 'operation': e['operation'], 'module_id': e.get('module_id'), 'card_bytes': 0}
                            for e in workflow_cost.journal(self.f.root) if workflow_cost.model_turn(e)]

    def leaf_plan(self, mid):
        """The fixture's plan for a leaf that holds three cases: one automation PATH per case, the others on its first."""
        plan, m = self.plan_of_one_case(mid), self.f.state()['modules'][mid]
        cases = m['case_ids']
        fixture = plan['source_closure']['verification']['fixture_contract_ref']  # the fixed inputs its allocation left to the leaf
        plan['source_closure'].update(json.loads(json.dumps(m['behavior_review'])))
        plan['source_closure']['verification']['fixture_contract_ref'] = fixture
        automation = next(p for p in plan['paths'] if p['kind'] == 'automation')
        for path in plan['paths']:
            path['case_id'] = cases[0]
        for cid in cases[1:]:
            plan['paths'].append({**json.loads(json.dumps(automation)), 'path_id': automation['path_id'] + '-' + cid, 'case_id': cid})
        for path in plan['paths']:
            if path['kind'] in behavior_contract.BEHAVIOR_KINDS:
                path['fixture_contract_ref'] = fixture
        added = [p['path_id'] for p in plan['paths'][-len(cases) + 1:]]
        plan['tasks'][0]['path_ids'] += added
        plan['dimension_trace'][0]['path_ids'] += added
        plan['dimension_trace'][0]['assertions'] += [{'path_id': pid, 'assertion_id': 'A1'} for pid in added]
        return plan

    def model_turn(self, step):
        f = self.f
        if step.get('operation') == 'decompose':  # the orchestrator confirms the drafted cut and narrows each leaf's write paths
            out = split_draft.write(f.root, step['module_id'], f.base / 'staging/module-orchestrator/draft')
            draft = read_json(Path(out['draft']['path']))
            for child in draft['children']:
                child['write_paths'] = [str(f.target / child['name'].lower())]
            f.call('decompose', {'plan_ref': f.ref('split.json', draft)}, module=step['module_id'])
        else:
            super().model_turn(step)


SEVEN = [{'feature_id': 'F-' + name.upper(), 'name': name, 'functional_path': 'Search/' + name, 'trigger': 'open ' + name,
          'observable_result': name + ' shown', 'requirement_ids': ['R1'], 'case_ids': ['C%d' % (3 * i + j + 1) for j in range(3)], 'evidence_refs': []}
         for i, name in enumerate(('Query', 'History', 'Detail', 'Share', 'Filter', 'Export', 'Settings'))]
RECORDED_TICKS = {'seven leaves': 11}  # the ticks a host that starts every line takes from the root's split to done, last recorded in VERIFICATION.md


class SevenLeafTests(ContinuousWalk):
    """Seven features cut into seven leaves, more than the run's parallel budget of five."""
    features = SEVEN

    def host_ticks(self, limit=80):
        return ContinuousRunTests.host_ticks(self, limit)

    def test_no_more_leaves_are_at_work_at_once_than_the_parallel_budget(self):
        ticks = self.host_ticks()
        budget = self.f.state()['max_parallel_modules']
        for tick in ticks:  # planning included, not only the workers the Ledger assigns
            self.assertLessEqual(len({mid for _, mid in tick if mid}), budget, tick)
        self.assertEqual(max(len({mid for _, mid in tick if mid}) for tick in ticks), budget)  # and the budget is used
        self.assertTrue(any(self.waiting))  # the leaves beyond it waited for a slot
        self.assertEqual(sorted(self.f.state()['modules']), ['M0%d' % (11 + i) for i in range(7)])
        if len(ticks) > RECORDED_TICKS['seven leaves'] > 0:
            import warnings
            warnings.warn('seven leaves took %d ticks, %d recorded' % (len(ticks), RECORDED_TICKS['seven leaves']))


RECORDED_ADAPTER = {'turns': {'global-orchestrator': 1, 'module-orchestrator': 1, 'spec-designer': 2, 'implementer': 2, 'test-runner': 2, 'auditor': 1},
                    'card_bytes': 19795}  # the same run whose project states the adapter that drives its functional paths


class AdapterRunTests(ContinuousWalk):
    """The project states a test adapter; the run's input does not repeat it."""
    def setUp(self):
        def config(f):
            script = f.base / 'adapter.py'
            script.write_text('import argparse,json,pathlib,runpy\np=argparse.ArgumentParser();p.add_argument("--query-file");p.add_argument("--result-file");a,_=p.parse_known_args()\n'
                              f'v=sorted({{runpy.run_path(str(c))["value"] for c in pathlib.Path({str(f.target)!r}).rglob("code.py")}})\n'
                              'json.dump({"assertions":[{"assertion_id":"A1","expected":2,"actual":v[0] if v else None,"passed":v==[2]}]},open(a.result_file,"w"))\n')
            return {'test_adapter': {'executable': sys.executable, 'args': [str(script)]}}
        real = test_source_changes.SourceChangeTests.register_root
        test_source_changes.SourceChangeTests.register_root = lambda t, features=None, global_paths=(): real(t, features, global_paths, config=config)
        try:
            super().setUp()
        finally:
            test_source_changes.SourceChangeTests.register_root = real

    def test_the_adapter_the_project_states_runs_the_functional_paths_without_a_model(self):
        self.assertEqual(self.f.state()['test_adapter']['args'][0].rsplit('/', 1)[-1], 'adapter.py')  # taken from the project, not the input
        record, taken = self.rehearse(RECORDED_ADAPTER)
        self.assertEqual(record['turns'], RECORDED_ADAPTER['turns'])  # a Test-Runner turn per leaf: its static review
        automation = [e for e in workflow_cost.journal(self.f.root) if e['operation'] == 'submit' and e['actor']['role'] == 'test-runner'
                      and e['request_id'].startswith('advance-')]
        self.assertTrue(automation)  # run by advance with the stated adapter

    def test_an_input_that_repeats_another_adapter_is_refused(self):
        import project_context
        from contracts import Rejected
        ref = self.f.state()['project_context_ref']
        stated = project_context.run_adapter({'project_context_ref': ref})
        self.assertEqual(project_context.run_adapter({'project_context_ref': ref, 'test_adapter': stated}), stated)
        with self.assertRaisesRegex(Rejected, 'test adapter mismatch'):
            project_context.run_adapter({'project_context_ref': ref, 'test_adapter': {'executable': sys.executable, 'args': ['other.py']}})


class GlobalPathWalk(ContinuousWalk):
    """The same run with a global path frozen as a command over one case: held by the leaf done first, it is a wave's
    integration test; held by the leaf done last, the final audit runs it."""
    case = 'C4'

    def setUp(self):
        import tempfile
        self.global_dir = Path(tempfile.mkdtemp()); self.addCleanup(__import__('shutil').rmtree, self.global_dir, True)
        script = self.global_dir / 'global.py'
        script.write_text('import argparse,json,pathlib,runpy\np=argparse.ArgumentParser();p.add_argument("--query-file");p.add_argument("--result-file");a=p.parse_args()\n'
                          'target=pathlib.Path(pathlib.Path(__file__).with_name("target.txt").read_text())\n'
                          'v=sorted({runpy.run_path(str(c))["value"] for c in target.rglob("code.py")})\n'
                          'json.dump({"assertions":[{"assertion_id":"A1","expected":2,"actual":v[0] if v else None,"passed":v==[2]}]},open(a.result_file,"w"))\n')
        self.global_path = {'path_id': 'GP1', 'case_id': self.case, 'expected_assertions': [{'assertion_id': 'A1', 'expected': 2}],
                            'command': {'argv': [sys.executable, str(script)], 'cwd': str(self.global_dir)}}
        real = test_source_changes.SourceChangeTests.register_root
        def register_root(t, features=None, global_paths=()):
            return real(t, features, [self.global_path])
        test_source_changes.SourceChangeTests.register_root = register_root
        self.addCleanup(setattr, test_source_changes.SourceChangeTests, 'register_root', real)
        super().setUp()
        (self.global_dir / 'target.txt').write_text(str(self.f.target))


class GlobalPathTests(GlobalPathWalk):
    def test_a_wave_s_global_path_is_dispatched_preflighted_and_run_by_the_ledger_in_a_prepared_run(self):
        record, taken = self.rehearse(RECORDED)  # the same model turns as without it
        journal = workflow_cost.journal(self.f.root)
        ran = [(e['operation'], e['actor']['role']) for e in journal if e['operation'] in ('integration-assign', 'integration-submit')
               or e['operation'] == 'context-submit' and e['actor']['instance_id'] == 'integration-test-runner']
        self.assertEqual(ran, [('integration-assign', 'global-orchestrator'), ('context-submit', 'test-runner'), ('integration-submit', 'test-runner')])
        self.assertEqual(self.f.state()['audit_results']['GP1']['quality'], 'green-passed')
        self.assertNotIn('global-orchestrator', {row['role'] for row in taken[len(self.setup_turns):]})  # no GO turn at the wave


class FinalGlobalPathTests(GlobalPathWalk):
    case = 'C1'  # held by the leaf done last: no wave boundary before the audit

    def test_a_global_path_left_to_the_final_audit_is_dispatched_preflighted_and_run_by_the_ledger(self):
        record, taken = self.rehearse(RECORDED)  # the same model turns: the Auditor reviews, the retest and its verdict are facts
        journal = workflow_cost.journal(self.f.root)
        self.assertEqual([e['operation'] for e in journal if e['operation'].startswith('integration')], [])
        ran = [(e['operation'], e['actor']['role']) for e in journal if e['operation'] in ('audit-assign', 'audit-test-assign', 'audit-test-submit', 'audit')]
        self.assertEqual(ran, [('audit-assign', 'global-orchestrator'), ('audit-test-assign', 'global-orchestrator'),
                               ('audit-test-submit', 'test-runner'), ('audit', 'auditor')])
        self.assertEqual(self.f.state()['audit_results']['GP1']['quality'], 'green-passed')


class ContinuousRunTests(ContinuousWalk):
    def test_a_run_from_its_registration_reaches_its_verdict(self):
        record, taken = self.rehearse(RECORDED)
        # what is left above the leaves is registering the root and confirming the cut the Ledger drafted
        self.assertEqual([(row['role'], row['operation']) for row in taken[:3]],
                         [('global-orchestrator', 'register'), ('module-orchestrator', 'decompose'), ('spec-designer', 'plan')])
        self.assertEqual(sorted(self.f.state()['modules']), ['M011', 'M012'])

    def test_a_host_that_starts_every_line_of_a_tick_codes_the_leaves_together_and_builds_each_while_nobody_writes(self):
        ticks = self.host_ticks()
        self.assertIn([('implementer', 'M011'), ('implementer', 'M012')], ticks)  # planned together, coded together
        for tick in ticks:  # one build unit: a leaf is built only while the other writes nothing
            roles = {role for role, _ in tick}
            self.assertFalse({'implementer', 'test-runner'} <= roles and len({mid for _, mid in tick}) > 1, tick)

    def host_ticks(self, limit=60):
        """A host that starts every model line of a tick: the (role, module) it started, tick by tick, ending with done."""
        import drive
        ticks, self.waiting = [], []
        for _ in range(limit):
            out = drive.drive(self.f.root, test_run_rehearsal.MO)
            self.waiting.append(out[-1].get('modules_waiting', 0))
            lines = [line for line in out if line['kind'] in ('dispatch', 'running', 'done')]
            ticks.append([(line.get('role'), line.get('module_id')) for line in lines])
            if not lines or lines[0]['kind'] == 'done':
                break
            for line in lines:  # every worker of the tick, as a host with free slots starts them
                st = self.f.state()
                self.model_turn(next(s for s in st['next_steps'] if s['module_id'] == line['module_id']) if line.get('module_id') else st['global_next_step'])
        self.assertEqual(ticks[-1], [(None, None)])  # the run ended: done
        return ticks

    def test_confirming_a_drafted_cut_reads_the_rules_of_a_hand_cut_only_on_demand(self):
        import ledger, reading
        ledger.advance_run(self.f.root, test_run_rehearsal.MO)
        step = next(s for s in self.f.state()['next_steps'] if s.get('operation') == 'decompose')
        resident = {(row['ref'], row['section']) for row in step['must_read']}
        on_demand = {(row['ref'], row['section']) for row in step['read_when_writing']}
        self.assertFalse(resident & set(reading.HAND_CUT))
        self.assertLessEqual(set(reading.HAND_CUT), on_demand)  # named with their purpose, read when the cut departs from the draft
        self.assertEqual(step['templates'], ['template/module-decomposition.json'] + [x for x in step['templates'] if 'telemetry' in x])


if __name__ == '__main__':
    unittest.main()
