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
RECORDED = {'turns': {'global-orchestrator': 1, 'module-orchestrator': 1, 'spec-designer': 2, 'implementer': 2, 'test-runner': 4, 'auditor': 1},
            'card_bytes': 19795}


class ContinuousWalk(test_run_rehearsal.RunWalk):
    """A run whose root has two features of three cases each, registered and nothing else."""
    def setUp(self):
        self.t = test_source_changes.SourceChangeTests(methodName='runTest'); self.f = self.t.register_root(FEATURES)
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


class ContinuousRunTests(ContinuousWalk):
    def test_a_run_from_its_registration_reaches_its_verdict(self):
        record, taken = self.rehearse(RECORDED)
        # what is left above the leaves is registering the root and confirming the cut the Ledger drafted
        self.assertEqual([(row['role'], row['operation']) for row in taken[:3]],
                         [('global-orchestrator', 'register'), ('module-orchestrator', 'decompose'), ('spec-designer', 'plan')])
        self.assertEqual(sorted(self.f.state()['modules']), ['M011', 'M012'])

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
