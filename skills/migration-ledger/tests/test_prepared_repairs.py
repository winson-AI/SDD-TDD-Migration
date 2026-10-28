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
from contracts import baseline, file_ref

# The turns last recorded in VERIFICATION.md after both leaves are first green: the repair and the audit around it.
RECORDED = {'trace': {'auditor': 2, 'spec-designer': 1, 'implementer': 1, 'test-runner': 1},
            'fix': {'auditor': 2, 'fixer': 1, 'test-runner': 1},
            'spec-gap': {'diagnostician': 1, 'spec-designer': 1, 'implementer': 1, 'test-runner': 1}}  # the leaf's own turns


class PreparedRepairWalk(test_continuous_run.ContinuousWalk):
    route = None  # the route the first code review writes for its finding
    gap = False  # the first automation of M011 finds what its SPEC left out

    def code(self, mid, a):
        out = super().code(mid, a)
        code = Path(out['code_files'][0]['path'])
        if a['role'] == 'fixer' or self.f.state()['modules'][mid].get('change_request_history'):  # the repair changes the code
            code.write_text(code.read_text() + 'count = 1\n')
            out['code_files'] = [file_ref(code)]; out['code_baseline'] = baseline(out['code_files'])
        return out

    def commands(self, mid, aid):
        argvs = super().commands(mid, aid)
        if self.gap and mid == 'M011':  # what the legacy shows besides the value: the count the plan never asked for
            script = Path(argvs['automation'][1])
            script.write_text(script.read_text().replace('v=runpy.run_path(', 'ns=runpy.run_path(').replace('["value"]\n', '\nv=ns["value"]\n')
                              .replace('json.dump({"assertions"', 'json.dump({**({} if "count" in ns else {"quality": "red-bug", "root_cause": {"category": "fidelity-gap", '
                                       '"summary": "the legacy query also shows its count", "confidence": "suspected", "owner": "M011", "next_action": "diagnose"}}), "assertions"')
                              + 'raise SystemExit(0 if "count" in ns else 1)\n')  # compared with the legacy, the screen differs
        return argvs

    def setUp(self):
        super().setUp()
        self.reviews = 0

    def model_turn(self, step):
        f, mid = self.f, step.get('module_id')
        if step.get('operation') == 'diagnose':  # the automation's failure is a gap in the SPEC, confirmed
            return f.call('diagnose', {'diagnosis_ref': f.ref('diagnosis-' + mid + '.md', 'the legacy query also shows its count; the SPEC omits it'),
                                       'owner': mid, 'root_cause': {'category': 'fidelity-gap', 'summary': 'count omitted', 'confidence': 'confirmed',
                                                                    'owner': mid, 'next_action': 'revise-spec'}}, role=step['role'], module=mid)
        if step.get('operation') == 'audit-code-review' and not self.route:
            return test_ledger.code_review(f)
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

    def repaired(self, name, start='audit-code-review', module=None):
        """The turns from the first step of the repair to the verdict (of one leaf, when named), counted by role, warned
        when they grow."""
        taken, st = self.walk(120)
        first = next(i for i, row in enumerate(taken) if row['operation'] == start)
        turns = {}
        for row in taken[first:]:
            if module and row['module_id'] != module:
                continue
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

    def test_a_finding_the_review_routes_to_its_owner_is_repaired_without_an_orchestrator(self):
        self.route = 'fix'
        turns, taken = self.repaired('fix')
        self.assertEqual(turns, RECORDED['fix'])  # collected, routed, dispatched, retested and judged by the Ledger
        self.assertEqual(self.f.state()['audit_code_review']['carried_modules'], ['M012'])

    def test_a_spec_gap_the_automation_finds_is_revised_in_the_leaf_and_its_code_updated(self):
        self.gap = True
        turns, taken = self.repaired('spec-gap', start='diagnose', module='M011')
        self.assertEqual(turns, RECORDED['spec-gap'])  # the change opened by itself, the added PATH reviewed by the Ledger
        self.assertTrue(any(k.startswith('SPEC-M011-added-') for k in self.f.state()['issues']))

if __name__ == '__main__':
    unittest.main()
