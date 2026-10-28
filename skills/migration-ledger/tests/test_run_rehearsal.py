"""A whole run walked by its cursor: a registered root split into a provider leaf and its dependent, both leaves planned,
coded and tested, then the unified audit. Every step the cursor marks mechanical is left to `ledger.py advance`; every other
one is a model's turn, scripted here and counted with the protocol bytes its card hands the model. The counts are reported,
not a gate: a change that adds turns or bytes warns with the walk. The top of this run is the fixture's hand split into a
provider and its dependent; test_continuous_run walks a run from the root's registration through the cut the Ledger drafts."""
import json
from pathlib import Path
import sys
import unittest
import warnings

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import spec_closure
import test_ledger
import test_source_changes
import workflow_cost
from contracts import baseline, file_ref
from execute_test import execute
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'migration-test/scripts'))
from harmony_stage import build as stage_result

MO = {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}
# The counts last recorded in VERIFICATION.md: model turns by role, and the most protocol bytes one turn's card handed a model.
RECORDED = {'turns': {'global-orchestrator': 3, 'module-orchestrator': 1, 'spec-designer': 2, 'implementer': 2, 'test-runner': 2, 'auditor': 1},
            'card_bytes': 19795}
RECORDED_RED = {'turns': {'global-orchestrator': 3, 'module-orchestrator': 1, 'spec-designer': 2, 'implementer': 2, 'test-runner': 3, 'fixer': 1, 'auditor': 1}, 'card_bytes': 19795}  # the same run whose first version of one leaf fails its automation


class RunWalk(unittest.TestCase):
    """A run walked by its cursor; what a model does is scripted in `model_turn`."""
    def setUp(self):
        self.t = test_source_changes.SourceChangeTests(methodName='runTest'); self.t.setUp(); self.addCleanup(self.t.doCleanups)
        self.f = self.t.f
        # the root's registration, split and global coverage happened in the fixture: the journal says who took a turn for them
        self.setup_turns = [{'role': e['actor']['role'], 'operation': e['operation'], 'module_id': e.get('module_id'), 'card_bytes': 0}
                            for e in workflow_cost.journal(self.f.root) if workflow_cost.model_turn(e)]

    red = ()

    def code(self, mid, a):
        f, m = self.f, self.f.state()['modules'][mid]
        code = Path(m['write_paths'][0]) / 'code.py'; code.parent.mkdir(exist_ok=True)
        code.write_text('value = %d\n' % (9 if mid in self.red and a['role'] == 'implementer' else 2))  # a red first version is fixed by the Fixer
        (code.parent / 'entry.py').write_text('from code import value\n'); (code.parent / 'test_code.py').write_text('from code import value\n')
        proof = f.ref('binding-' + a['assignment_id'] + '.md', 'Real scoped implementation')
        return {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': mid, 'assignment_id': a['assignment_id'],
                'actor_instance_id': a['instance_id'], 'freeze_id': m['freeze_id'], 'code_files': [file_ref(code)],
                'code_baseline': baseline([file_ref(code)]), 'task_trace': [{'task_id': 'T1', 'files': [str(code)]}],
                'production_binding_evidence': proof,
                'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('diag.log', '0 errors')},
                'dimension_evidence': [{'item_id': self.t.logic_item(mid), 'task_ids': ['T1'], 'summary': 'Implemented scoped behavior', 'evidence_refs': [proof]}],
                **({'fix_note_ref': f.ref('fix-note-' + a['assignment_id'] + '.json', {'root_cause': 'value 9 where 2 is expected', 'strategy': 'return 2',
                                                                                         'applicability': 'this module', 'risks': 'none'})} if a['role'] == 'fixer' else {})}

    def commands(self, mid, aid):
        """What a Test-Runner runs for the PATHs that do not run by themselves: the static review and a script adapter."""
        f, m = self.f, self.f.state()['modules'][mid]
        code = Path(m['write_paths'][0]) / 'code.py'
        notes = f.ref('static-notes-' + aid + '.md', 'Reviewed production entry for value')
        review = f.ref('static-review-' + aid + '.json', {'schema_version': 1, 'run_id': 'demo', 'module_id': mid, 'path_id': mid + '-S',
            'freeze_id': m['freeze_id'], 'code_baseline': m['code_baseline'],
            'scenarios': [{'scenario_id': 'SCN-' + mid + '-normal', 'requirement_id': 'R1', 'status': 'passed', 'summary': 'value reaches entry',
                           'production_symbols': [{'path': str(code), 'symbol': 'value'}],
                           'reached_from': {'path': str(code.parent / 'entry.py'), 'symbol': 'value'},
                           'test_refs': [{'path': str(code.parent / 'test_code.py'), 'symbol': 'value'}], 'evidence_refs': [notes]}],
            'anti_patterns': {k: {'status': 'absent', 'note': 'reviewed', 'evidence_refs': [notes]} for k in spec_closure.ANTI_PATTERNS}})
        script = f.root / 'staging/test-runner' / (aid + '.py'); script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text('import argparse,json,runpy\np=argparse.ArgumentParser();p.add_argument("--query-file");p.add_argument("--result-file");a=p.parse_args()\n'
                          f'v=runpy.run_path({str(code)!r})["value"]\n'
                          'json.dump({"assertions":[{"assertion_id":"A1","expected":2,"actual":v,"passed":v==2}]},open(a.result_file,"w"))\n')
        return {'static': [sys.executable, spec_closure.__file__, '--review', review['path'], '--target-root', str(f.target)],
                'automation': [sys.executable, str(script)]}

    def model_turn(self, step):
        f, op, mid = self.f, step.get('operation'), step.get('module_id')
        if op == 'plan':
            plan = self.t.plan(mid)
            if f.state().get('test_design_required'):
                from test_design_stage import prepare_design
                prepare_design(f, plan, mid)
            f.call('plan', {'plan_ref': f.ref('plan-' + mid + '.json', plan)}, role='spec-designer', module=mid)
        elif op == 'plan-review':
            m = f.state()['modules'][mid]
            f.call('plan-review', {'review_ref': f.ref('review-' + mid + '.json', {
                'schema_version': 1, 'plan_hash': m['plan_hash'], 'reviewer_instance_id': 'module-orchestrator', 'semantic_change': False,
                'authorization_change': False, 'unresolved_questions': [], 'reason': 'clear plan',
                'evidence_refs': [f.ref('review-' + mid + '.md', 'scope and tests checked')]})}, module=mid)
        elif op == 'await-result' and step['role'] in ('implementer', 'fixer'):
            a = f.state()['modules'][mid]['assignments'][step['assignment_id']]
            if a['role'] == 'fixer' and not a.get('context_ref'):  # the Fixer says it can start: a repair round is spent from here
                f.record(f.report('fixing', module=mid, instance=a['instance_id']))
            f.call('submit', {'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token'],
                              'result_ref': f.ref(a['assignment_id'] + '.json', self.code(mid, a))}, role=a['role'], instance=a['instance_id'], module=mid)
        elif op == 'await-result' and step['role'] == 'test-runner':
            m = f.state()['modules'][mid]; a = m['assignments'][step['assignment_id']]
            paths = {p['path_id']: p for p in m['plan']['paths']}
            argvs = self.commands(mid, a['assignment_id'])
            pids = a['execution_contract']['path_ids']
            chosen = {pid: paths[pid].get('command', {}).get('argv') or argvs[paths[pid].get('kind') or 'automation'] for pid in pids}
            report = f.report('building' if a['test_scope'] == 'build' else 'testing', module=mid, instance=a['instance_id'])
            report['execution'] = {'argv': chosen[pids[0]], 'cwd': str(f.target), 'environment_ref': f.ref('environment.md', 'Python fixture'),
                                   'commands': {pid: {'argv': argv, 'cwd': str(f.target)} for pid, argv in chosen.items()}}
            f.record(report)
            receipts = [execute(f.root, mid, a['assignment_id'], pid, chosen[pid], str(f.target),
                                f.root / ('runs/build' if (paths[pid].get('kind') or 'automation') in ('build', 'unit') else 'runs/harmony/automation') / (a['assignment_id'] + pid))
                        for pid in pids]
            f.call('submit', {'assignment_id': a['assignment_id'], 'fencing_token': a['fencing_token'],
                              'result_ref': f.ref(a['assignment_id'] + '-result.json', stage_result(f.root, mid, a['assignment_id'], receipts))},
                   role='test-runner', instance=a['instance_id'], module=mid)
        elif op == 'audit-code-review':
            test_ledger.code_review(f)
        elif op == 'audit':  # the Auditor's verdict on a run with nothing left to retest
            s = f.state(); scope = ledger.audit_scope(s)
            f.call('audit', {'report_ref': f.ref('audit.json', {'schema_version': 1, 'kind': 'audit-review', 'run_id': 'demo', 'module_id': 'GLOBAL',
                'assignment_id': s['audit_assignment']['assignment_id'], 'actor_instance_id': 'auditor', 'freeze_id': scope['freeze_id'],
                'code_baseline': scope['code_baseline'], 'snapshot': s['audit_assignment']['snapshot'], 'paths': [],
                'execution_status': 'no-retest-needed', 'review_ref': f.ref('audit-review.md', 'every module result and the code review read')})},
                role='auditor', module=None)
        elif op == 'audit-assign':
            f.call('audit-assign', {**(step.get('payload') or {}), 'assignment_id': 'AUD1', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        else:
            self.fail('no scripted model turn for ' + json.dumps({k: step.get(k) for k in ('module_id', 'operation', 'role', 'reason')}))

    def walk(self, limit=80):
        f, taken = self.f, []
        for _ in range(limit):
            moved = True
            while moved:  # as a drive tick does: what the run's flows submit may unlock a module's step, and back
                moved = False
                for mid in [s['module_id'] for s in f.state()['next_steps']]:  # leaves and parents
                    moved |= bool(ledger.advance(f.root, MO, mid)['applied'])
                moved |= bool(ledger.advance_run(f.root, MO))  # and the run's own fixed flows
            st = f.state()
            # a ready step, or a dispatched worker's turn
            steps = [s for s in st['next_steps'] if (s.get('ready') or s.get('operation') == 'await-result') and s.get('operation') and not s.get('mechanical')]
            g = st['global_next_step']
            if g.get('operation') and not g.get('mechanical') and (g.get('ready') or g.get('reason') == 'audit-running'):  # the audit is the Auditor's running turn
                steps.append(g)
            if not steps:
                return taken, st
            step = steps[0]
            taken.append({'role': step.get('role'), 'operation': step.get('operation'), 'module_id': step.get('module_id'),
                          'card_bytes': sum(row['bytes'] for row in step.get('must_read', []))})
            self.model_turn(step)
        self.fail('the run did not settle: ' + json.dumps(taken))

    def rehearse(self, recorded=None):
        recorded = recorded or RECORDED
        taken, st = self.walk()
        taken = self.setup_turns + taken
        turns = {}
        for row in taken:
            turns[row['role']] = turns.get(row['role'], 0) + 1
        record = {'turns': turns, 'card_bytes': max(row['card_bytes'] for row in taken)}
        if sum(turns.values()) > sum(recorded['turns'].values()) or record['card_bytes'] > recorded['card_bytes']:
            warnings.warn('the run took %s, recorded %s: %s' % (json.dumps(record), json.dumps(recorded), json.dumps(taken)))
        self.assertEqual(st['quality'], 'green-passed')  # the run reached its verdict
        return record, taken


class RunRehearsalTests(RunWalk):
    def test_a_run_reaches_its_audit_and_its_model_turns_and_card_bytes_are_reported(self):
        self.rehearse()
        verdict = next(e for e in workflow_cost.journal(self.f.root) if e['operation'] == 'audit')
        self.assertEqual((verdict['actor']['role'], verdict['request_id'][:12]), ('auditor', 'advance-run-'))  # a clean review is the verdict

    def test_a_run_whose_first_version_fails_is_repaired_and_reaches_its_audit(self):
        self.red = ('M001',)
        record, taken = self.rehearse(RECORDED_RED)
        self.assertIn(('fixer', 'await-result', 'M001'), [(row['role'], row['operation'], row['module_id']) for row in taken])
        self.assertNotIn('diagnostician', record['turns'])  # a failed assertion of its own goes to the Fixer


if __name__ == '__main__':
    unittest.main()
