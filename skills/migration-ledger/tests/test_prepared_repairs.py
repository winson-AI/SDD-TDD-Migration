"""Repairs walked in a prepared run - context readiness, static review and unit tests on, as every run `prepare` creates:
what the unified audit sends back, routed by the finding itself, is repaired with the turns judgment takes. The counts are
reported, not a gate."""
import json
from pathlib import Path
import sys
import unittest
import warnings

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_continuous_run
import test_ledger

# The turns last recorded in VERIFICATION.md after both leaves are first green: the repair and the audit around it.
RECORDED = {'trace': {'auditor': 2, 'spec-designer': 1, 'implementer': 1, 'test-runner': 2}}


class PreparedRepairWalk(test_continuous_run.ContinuousWalk):
    route = None  # the route the first code review writes for its finding

    def setUp(self):
        super().setUp()
        self.reviews = 0

    def model_turn(self, step):
        f, mid = self.f, step.get('module_id')
        if step.get('operation') == 'audit-code-review':
            self.reviews += 1
            if self.reviews > 1:  # after the repair: what it changed
                return test_ledger.code_review(f, modules=step.get('review_modules'))
            category = 'planning-gap' if self.route == 'trace' else 'code'
            test_ledger.code_review(f, findings=[{
                'finding_id': 'CR-1', 'source_module_id': 'M011', 'category': 'fidelity', 'path_id': None, 'affected_module_ids': ['M011'],
                'root_cause': {'category': category, 'summary': 'the legacy query also shows its count', 'confidence': 'confirmed',
                               'owner': 'M011', 'next_action': 'revise'},
                'analysis_ref': f.ref('finding-analysis.md', 'the legacy query shows a count the SPEC never stated'),
                'route': {'action': self.route, 'owner_module_ids': ['M011']}}])
        elif step.get('operation') == 'plan' and (f.state()['modules'][mid].get('change_request')):
            plan = self.t.plan(mid)  # written again for the reopened SPEC, with the PATH the SPEC missed
            path = next(p for p in plan['paths'] if p['kind'] == 'automation')
            plan['paths'].append({**json.loads(json.dumps(path)), 'path_id': path['path_id'] + '-COUNT'})
            plan['tasks'][0]['path_ids'].append(path['path_id'] + '-COUNT')
            plan['dimension_trace'][0]['path_ids'].append(path['path_id'] + '-COUNT')
            plan['dimension_trace'][0]['assertions'].append({'path_id': path['path_id'] + '-COUNT', 'assertion_id': 'A1'})
            if f.state().get('test_design_required'):
                from test_design_stage import prepare_design
                prepare_design(f, plan, mid)
            f.call('plan', {'plan_ref': f.ref('revised-plan-' + mid + '.json', plan)}, role='spec-designer', module=mid)
        else:
            super().model_turn(step)

    def repaired(self, name):
        """The turns after the first review, counted by role, warned when they grow."""
        taken, st = self.walk(120)
        first = next(i for i, row in enumerate(taken) if row['operation'] == 'audit-code-review')
        turns = {}
        for row in taken[first:]:
            turns[row['role']] = turns.get(row['role'], 0) + 1
        if sum(turns.values()) > sum(RECORDED[name].values()):
            warnings.warn('%s repair took %s, recorded %s: %s' % (name, turns, RECORDED[name], json.dumps(taken[first:])))
        self.assertEqual(st['quality'], 'green-passed')
        return turns, taken[first:]


class PreparedRepairTests(PreparedRepairWalk):
    def test_a_spec_gap_the_audit_traces_back_is_revised_by_its_leaf_and_the_code_kept(self):
        self.route = 'trace'
        turns, taken = self.repaired('trace')
        self.assertEqual(turns, RECORDED['trace'])  # no orchestrator turn: the confirmed cause opened the change, the added PATH was reviewed by the Ledger
        s = self.f.state()
        trace = next(v for k, v in s['issues'].items() if k.startswith('TRACE-'))
        self.assertEqual(set(trace['resolved']), {'M011'})  # answered by the leaf's revision
        self.assertTrue(any(k.startswith('SPEC-M011-added-') for k in s['issues']))
        self.assertEqual(s['audit_code_review']['carried_modules'], ['M012'])  # the leaf that was not revised is not reviewed again


if __name__ == '__main__':
    unittest.main()
