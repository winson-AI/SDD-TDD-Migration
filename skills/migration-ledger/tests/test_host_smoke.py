"""A host that does what /sdd-run says and nothing else: after the root's registration it runs `drive.py` as a command
each tick, reads only the lines it prints, starts the role a `dispatch` or `running` line names with the card it hands,
submits a `host` line through `ledger.py apply`, and stops on the `done` line. The roles stand in for models and are
scripted in-process, as in the continuous rehearsal; the host side is only these commands. A tick with nothing to act on
and no end would leave such a host waiting forever, so it fails the walk."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import drive
import test_continuous_run
from test_run_rehearsal import MO

SCRIPTS = Path(drive.__file__).resolve().parent
LINE_BYTES = 1024  # what the host reads per line: no evidence, no state; the longest is a question for the user


class HostSmokeTests(test_continuous_run.ContinuousWalk):
    def command(self, script, *args):
        out = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stdout[-2000:] + out.stderr[-2000:])
        return out.stdout

    def host_line(self, line):
        """Submit from the drive row. The session receipt stands in for the host's native session manager."""
        request = {key: line[key] for key in ('run_id', 'module_id', 'expected_revision', 'operation')}
        actor = {'role': 'host', 'instance_id': 'host'}
        if line['kind'] == 'rotate':
            rotation = line['session_rotate']
            checkpoint = rotation['checkpoint']
            ref = self.f.ref('rotation-checkpoint.json', checkpoint)
            session_id = 'restored-' + checkpoint['previous_session_id']
            payload = {'role': checkpoint['role'], 'session_id': session_id, 'reason': 'context-rotation', 'checkpoint_ref': ref}
            if rotation['host_receipt_required']:
                payload['host_receipt_ref'] = self.f.ref('rotation-receipt.json', {
                    'producer': 'host', 'status': 'restored', 'checkpoint_ref': ref, 'session_id': session_id,
                    **{key: checkpoint[key] for key in ('run_id', 'module_id', 'role', 'previous_session_id')},
                    'restored_refs': checkpoint['resume_refs'],
                    'evidence_refs': [self.f.ref('session-restore.log', 'Fixture created an independent session')]})
            request.update(operation='session', payload=payload)
            if line['module_id']:
                actor = MO
        else:
            request['payload'] = line['payload']
        request_id = 'host-' + request['operation'] + '-' + str(line['module_id']) + '-' + str(line['expected_revision'])
        ref = self.f.ref('staging/host/' + request_id + '.json', {'schema_version': 1, 'request_id': request_id, **request})
        principal = self.f.ref('staging/host/principal.json', actor)
        self.command('ledger.py', 'apply', '--root', str(self.f.root), '--request', ref['path'], '--host-context', principal['path'])

    def walk_host(self):
        seen, started, signals = [], set(), []
        for _ in range(40):
            lines = [json.loads(text) for text in self.command('drive.py', '--root', str(self.f.root), '--host-context', json.dumps(MO)).splitlines()]
            self.assertEqual(lines[-1]['kind'], 'tick')
            self.assertLess(max(len(json.dumps(line, ensure_ascii=False).encode()) for line in lines if line['kind'] != 'rotate'), LINE_BYTES)
            self.assertFalse([line for line in lines if line['kind'] in ('person', 'refused')], lines)  # nothing here asks a person
            signals += [json.dumps(line, sort_keys=True) for line in lines if line['kind'] == 'signal' and line['reason'] != 'attention-report']
            done = [line for line in lines if line['kind'] == 'done']
            if done:
                break
            work = [line for line in lines if line['kind'] in ('dispatch', 'running', 'host', 'rotate')]
            new = [line for line in work if line['kind'] != 'running' or line['assignment_id'] not in started]
            self.assertTrue(new, 'nothing to act on and no end: ' + json.dumps(lines))  # every worker here answers in its turn
            for line in new:
                if line['kind'] == 'running':
                    started.add(line['assignment_id'])
                seen.append((line['role'], 'rotate' if line['kind'] == 'rotate' else line['operation'], line.get('module_id')))
                if line['kind'] in ('host', 'rotate'):
                    self.host_line(line)
                    continue
                self.assertTrue(Path(line['card']).is_file(), line)  # the role is started with the card the line hands it
                self.model_turn(line)
        else:
            self.fail('the run did not settle: ' + json.dumps(seen))
        self.assertEqual((done[0]['quality'], done[0]['reason']), ('green-passed', 'await-delivery-authorization'))  # the user is asked to deliver
        self.assertTrue(Path(done[0]['report']).is_file())
        cursor = json.loads(self.command('ledger.py', 'status', '--root', str(self.f.root), '--view', 'cursor'))
        self.assertEqual(cursor['quality'], 'green-passed')
        self.assertEqual(len(signals), len(set(signals)))  # a standing signal reached the host once
        return seen

    def test_a_host_running_only_drive_lines_takes_the_run_from_registration_to_its_verdict(self):
        seen = self.walk_host()
        # the host started the same model turns the continuous rehearsal counts, register aside
        roles = {}
        for role, *_ in seen:
            roles[role] = roles.get(role, 0) + 1
        expected = dict(test_continuous_run.RECORDED['turns'], **{'global-orchestrator': 0})
        self.assertEqual({k: v for k, v in roles.items() if v}, {k: v for k, v in expected.items() if v})


    def test_observed_automation_failure_revises_one_leaf_and_keeps_the_other_green(self):
        f = self.f
        self.red = ('M011',)
        leaf_plan, model_turn = self.t.plan, self.model_turn
        before = {}

        def revise_plan(mid):
            plan = leaf_plan(mid)
            if mid == 'M011' and before:
                path = copy.deepcopy(next(p for p in plan['paths'] if p['kind'] == 'automation'))
                path.update(path_id='M011-P-FIDELITY', name='Verify the discovered fidelity obligation')
                plan['paths'].append(path)
                plan['tasks'][0]['path_ids'].append(path['path_id'])
                trace = plan['dimension_trace'][0]
                trace['path_ids'].append(path['path_id'])
                trace['assertions'].append({'path_id': path['path_id'], 'assertion_id': 'A1'})
            return plan

        def diagnose_or_act(line):
            if line['operation'] == 'plan' and line['module_id'] == 'M011' and not before:
                state = f.state(); module = state['modules']['M011']
                step = next(step for step in state['next_steps'] if step['module_id'] == 'M011')
                f.call('session', module='M011', request={'schema_version': 1, 'request_id': 'old-implementer-session',
                       'run_id': state['run_id'], 'module_id': 'M011', 'expected_revision': module['revision'], 'operation': 'session',
                       'payload': {'role': 'implementer', 'session_id': 'old-implementer'},
                       'hint': {'session_id': 'old-implementer', 'card_sha256': step['card_sha256'],
                                'context_inputs': [{'kind': 'log', 'ref': f.ref('large.log', 'x' * 100001)}]}})
            if line['operation'] != 'diagnose':
                return model_turn(line)
            self.assertEqual((line['module_id'], line['role']), ('M011', 'diagnostician'))
            state = f.state()
            self.assertEqual(state['modules']['M011']['results']['M011-P']['root_cause']['confidence'], 'observed')
            self.assertEqual(state['modules']['M012']['phase'], 'completed')
            before.update(run_id=state['run_id'], changed=state['modules']['M011'], peer=state['modules']['M012'])
            evidence = f.ref('legacy-fidelity.md', 'The legacy behavior requires normalization before displaying the value')
            f.call('diagnose', {'diagnosis_ref': evidence, 'owner': 'M011', 'root_cause': {'category': 'fidelity-gap',
                   'confidence': 'confirmed', 'summary': 'Normalization is missing from the plan', 'owner': 'M011',
                   'next_action': 'revise-spec', 'evidence_refs': [evidence]}}, role=line['role'], module='M011')
            self.red = ()

        self.t.plan, self.model_turn = revise_plan, diagnose_or_act
        seen = self.walk_host()
        self.assertIn(('implementer', 'rotate', 'M011'), seen)
        self.assertEqual(seen.count(('spec-designer', 'plan', 'M011')), 2)
        self.assertNotIn(('fixer', 'await-result', 'M011'), seen)
        state = f.state(); changed, peer = state['modules']['M011'], state['modules']['M012']
        self.assertEqual(state['run_id'], before['run_id'])
        self.assertNotEqual(changed['freeze_id'], before['changed']['freeze_id'])
        self.assertEqual(changed['results']['M011-P']['retest_of'], before['changed']['results']['M011-P']['test_run_id'])
        self.assertEqual(peer['freeze_id'], before['peer']['freeze_id'])
        self.assertEqual(peer['results'], before['peer']['results'])
        report = json.loads(Path(state['migration_report']['json']).read_text())
        self.assertTrue(report['automation']['tasks']['M011/T1']['all_required_paths_passed'])


if __name__ == '__main__':
    unittest.main()
