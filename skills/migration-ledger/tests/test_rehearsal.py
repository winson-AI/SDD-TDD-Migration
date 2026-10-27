"""A leaf walked from its first plan to its completion by following the cursor alone: every step the cursor marks mechanical
is left to `ledger.py advance`, every other one is a model's turn and is counted. The count is a ratchet: a change that adds
a model turn to the leaf's loop fails here."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
import ledger
import test_ledger
from contracts import baseline, file_ref
from execute_test import execute
from harmony_stage import build as stage_result

MO = {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}
MODEL_TURNS = 4  # plan, plan review, coding, automation run (a device PATH)


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state(); f.root = f.base / 'rehearsal'
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec',
                                                     'new_architecture', 'global_paths')},
                        'dimension_slicing_required': False, 'split_testing_required': True, 'context_readiness_required': False}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'write_paths': [str(f.target / 'm1')]}, role='global-orchestrator', module=None)
        f.global_plan()
        self.adapter = f.base / 'adapter.py'
        self.adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');"
                                "a=p.parse_args()\njson.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':2,'passed':True}]},open(a.result_file,'w'))\n")

    def plan(self):
        f = self.f; p = f.plan()
        p['paths'][0]['kind'] = 'automation'
        command = lambda: {'argv': [sys.executable, '-c', 'raise SystemExit(0)'], 'cwd': str(f.target), 'timeout_seconds': 20,
                           'selection_ref': f.ref('selection.md', 'the module build and its unit tests')}
        p['paths'] += [{'path_id': 'B1', 'kind': 'build', 'name': 'compile', 'case_id': 'C1', 'requirement_id': 'R1', 'required': True,
                        'expected_assertions': [{'assertion_id': 'BUILD-EXIT', 'expected': 0}], 'command': command()},
                       {'path_id': 'U1', 'kind': 'unit', 'name': 'logic unit tests', 'case_id': 'C1', 'requirement_id': 'R1', 'required': True,
                        'expected_assertions': [{'assertion_id': 'UNIT-EXIT', 'expected': 0}], 'command': command()}]
        p['tasks'][0]['path_ids'] += ['B1', 'U1']
        return p

    def model_turn(self, step):
        """What a model would do at a step the cursor does not mark mechanical, scripted."""
        f, op = self.f, step.get('operation')
        m = f.state()['modules']['M001']
        if op == 'plan':
            f.call('plan', {'plan_ref': f.ref('rehearsal-plan.json', self.plan())}, role='spec-designer')
        elif op == 'plan-review':
            f.call('plan-review', {'review_ref': f.ref('review.json', {
                'schema_version': 1, 'plan_hash': m['plan_hash'], 'reviewer_instance_id': 'module-orchestrator', 'semantic_change': False,
                'authorization_change': False, 'unresolved_questions': [], 'reason': 'clear plan',
                'evidence_refs': [f.ref('review.md', 'scope and tests checked')]})})
        elif op == 'accept':
            f.call('accept', {'assignment_id': step['assignment_id']})
        elif op == 'await-result':
            a = m['assignments'][step['assignment_id']]
            principal = {'role': a['role'], 'instance_id': a['instance_id']}
            if a['role'] == 'implementer':
                source = f.target / 'm1/code.py'; source.parent.mkdir(exist_ok=True); source.write_text('value = 2\n')
                refs = [file_ref(source)]
                result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001', 'assignment_id': a['assignment_id'],
                          'actor_instance_id': a['instance_id'], 'freeze_id': a['freeze_id'], 'code_files': refs, 'code_baseline': baseline(refs),
                          'task_trace': [{'task_id': 'T1', 'files': [str(source)]}],
                          'production_binding_evidence': f.ref('binding.txt', 'real binding reviewed'),
                          'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('diag.log', '0 errors')}}
            else:
                paths = {p['path_id']: p for p in m['plan']['paths']}
                receipts = []
                for pid in a['execution_contract']['path_ids']:
                    command = paths[pid].get('command')
                    argv = command['argv'] if command else [sys.executable, str(self.adapter)]
                    receipts.append(execute(f.root, 'M001', a['assignment_id'], pid, argv, str(f.target), f.base / ('run-' + a['assignment_id'] + pid)))
                result = stage_result(f.root, 'M001', a['assignment_id'], receipts)
            ledger.apply(f.root, {'schema_version': 1, 'request_id': 'r-' + a['assignment_id'], 'run_id': 'demo', 'module_id': 'M001',
                                  'expected_revision': m['revision'], 'operation': 'submit',
                                  'payload': {'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token'],
                                              'result_ref': f.ref('result-' + a['assignment_id'] + '.json', result)}}, principal)
        else:
            self.fail('no scripted model turn for ' + str(op))

    def walk(self, limit=40):
        turns = []
        for _ in range(limit):
            ledger.advance(self.f.root, MO, 'M001')  # every mechanical step
            step = next(s for s in self.f.state()['next_steps'] if s.get('module_id') == 'M001')
            if self.f.state()['modules']['M001']['phase'] == 'completed':
                return turns
            turns.append((step.get('operation'), step.get('role'), step.get('test_scope') or (step.get('assignment_id') or '')[:4]))
            self.model_turn(step)
        self.fail('the leaf did not complete: ' + json.dumps(turns))

    def test_a_leaf_reaches_its_completion_within_the_model_turn_ratchet(self):
        turns = self.walk()
        self.assertLessEqual(len(turns), MODEL_TURNS, turns)
        self.assertEqual([op for op, *_ in turns][:2], ['plan', 'plan-review'])


if __name__ == '__main__':
    unittest.main()
