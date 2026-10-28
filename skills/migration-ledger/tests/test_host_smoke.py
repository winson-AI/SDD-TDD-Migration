"""A host that does what /sdd-run says and nothing else: after the root's registration it runs `drive.py` as a command
each tick, reads only the lines it prints, starts the role a `dispatch` or `running` line names with the card it hands,
submits a `host` line through `ledger.py apply`, and stops on the `done` line. The roles stand in for models and are
scripted in-process, as in the continuous rehearsal; the host side is only these commands. A tick with nothing to act on
and no end would leave such a host waiting forever, so it fails the walk."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import drive
import ledger
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
        """What the host submits itself, as `ledger.py apply`."""
        s = ledger.read_events(self.f.root)[0]
        mid = line.get('module_id')
        request = self.f.base / 'staging/host' / ('request-%d.json' % s['last_sequence'])
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text(json.dumps({'schema_version': 1, 'request_id': 'host-%d' % s['last_sequence'], 'run_id': s['run_id'], 'module_id': mid,
                                       'expected_revision': s['modules'][mid]['revision'] if mid in s['modules'] else s['revision'],
                                       'operation': line['operation'], 'payload': line['payload']}))
        principal = self.f.base / 'staging/host/principal.json'
        principal.write_text(json.dumps({'role': 'host', 'instance_id': 'host'}))
        self.command('ledger.py', 'apply', '--root', str(self.f.root), '--request', str(request), '--host-context', str(principal))

    def test_a_host_running_only_drive_lines_takes_the_run_from_registration_to_its_verdict(self):
        seen, started, signals = [], set(), []
        for _ in range(40):
            lines = [json.loads(text) for text in self.command('drive.py', '--root', str(self.f.root), '--host-context', json.dumps(MO)).splitlines()]
            self.assertEqual(lines[-1]['kind'], 'tick')
            self.assertLess(max(len(json.dumps(line, ensure_ascii=False).encode()) for line in lines), LINE_BYTES)
            self.assertFalse([line for line in lines if line['kind'] in ('person', 'refused')], lines)  # nothing here asks a person
            signals += [json.dumps(line, sort_keys=True) for line in lines if line['kind'] == 'signal' and line['reason'] != 'attention-report']
            done = [line for line in lines if line['kind'] == 'done']
            if done:
                break
            work = [line for line in lines if line['kind'] in ('dispatch', 'running', 'host')]
            new = [line for line in work if (line['kind'], line.get('module_id'), line['operation'], line.get('assignment_id')) not in started]
            self.assertTrue(new, 'nothing to act on and no end: ' + json.dumps(lines))  # every worker here answers in its turn
            for line in new:
                key = (line['kind'], line.get('module_id'), line['operation'], line.get('assignment_id'))
                started.add(key)
                seen.append((line['role'], line['operation'], line.get('module_id')))
                if line['kind'] == 'host':
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
        # the host started the same model turns the continuous rehearsal counts, register aside
        roles = {}
        for role, *_ in seen:
            roles[role] = roles.get(role, 0) + 1
        expected = dict(test_continuous_run.RECORDED['turns'], **{'global-orchestrator': 0})
        self.assertEqual({k: v for k, v in roles.items() if v}, {k: v for k, v in expected.items() if v})


if __name__ == '__main__':
    unittest.main()
