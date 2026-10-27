"""The host's loop as one command: what is mechanical is submitted, what needs a model comes back as one line each."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import drive
import test_rehearsal

MO = test_rehearsal.MO


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.r = test_rehearsal.RehearsalTests(methodName='runTest'); self.r.start(adapter_stated=True); self.addCleanup(self.r.doCleanups)
        self.f = self.r.f

    def lines(self, **kw):
        return drive.drive(self.f.root, MO, **kw)

    def test_a_leaf_is_driven_to_completion_with_one_line_per_model_turn(self):
        seen = []
        for _ in range(10):
            lines = self.lines()
            work = [line for line in lines if line['kind'] in ('dispatch', 'running') and line.get('module_id')]
            if not work:
                break
            line = work[0]
            seen.append((line['kind'], line['operation'], line['role']))
            self.assertLess(len(json.dumps(line, ensure_ascii=False)), 400)  # what the host reads per step
            step = next(s for s in self.f.state()['next_steps'] if s['module_id'] == line['module_id'])
            self.r.model_turn(step)
        self.assertEqual(seen, [('dispatch', 'plan', 'spec-designer'), ('running', 'await-result', 'implementer')])
        self.assertEqual(self.f.state()['modules']['M001']['phase'], 'completed')
        lines = self.lines()
        self.assertEqual([(line['kind'], line.get('operation')) for line in lines], [('dispatch', 'audit-code-review'), ('tick', None)])  # the run's turn next

    def test_the_command_prints_lines_and_waits_on_the_journal_only_when_nothing_is_to_dispatch(self):
        out = subprocess.run([sys.executable, str(Path(drive.__file__)), '--root', str(self.f.root), '--host-context', json.dumps(MO), '--wait', '30'],
                             capture_output=True, text=True, timeout=60)
        lines = [json.loads(line) for line in out.stdout.splitlines()]
        self.assertEqual([line['kind'] for line in lines], ['dispatch', 'tick'])  # a dispatch is due: no wait
        self.assertTrue(Path(lines[0]['card']).is_file())
        drive.POLL_SECONDS = 0.05; self.addCleanup(setattr, drive, 'POLL_SECONDS', 1)
        self.r.model_turn(next(s for s in self.f.state()['next_steps'] if s['module_id'] == 'M001'))
        lines = self.lines(wait=0.2)  # only a worker running: it follows the journal, then hands back what it saw
        self.assertEqual([line['kind'] for line in lines], ['running', 'tick'])


class SessionReuseTests(unittest.TestCase):
    def test_the_fixer_line_names_the_implementer_session_to_resume_and_its_instance(self):
        import test_ledger
        f = test_ledger.FlowTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        f.call('session', {'role': 'implementer', 'session_id': 'S-IMP'})
        f.implementation()
        a, result = f.make_test_result(quality='red-bug'); f.submit(result, a)
        lines = drive.drive(f.root, MO)
        fixer = next(line for line in lines if line.get('role') == 'fixer')
        self.assertEqual((fixer['kind'], fixer['session_id'], fixer['session_affinity']), ('running', 'S-IMP', 'implementer'))
        self.assertEqual(fixer['instance_id'], f.state()['modules']['M001']['assignments'][fixer['assignment_id']]['instance_id'])
        self.assertTrue(Path(fixer['card']).is_file() and fixer['card_bytes'] > 0)


    def test_a_resumed_session_is_handed_only_what_it_has_not_read(self):
        import reading, tempfile
        rows = reading.card({}, {}, {'role': 'fixer', 'operation': 'submit'})
        with tempfile.TemporaryDirectory() as root:
            whole = drive.card(root, {'must_read': rows})
            resumed = drive.card(root, {'must_read': rows, 'must_read_new': rows[:2], 'session_id': 'S-IMP'})
        self.assertEqual(resumed['resumed_from_bytes'], sum(r['bytes'] for r in rows))
        self.assertLess(resumed['card_bytes'], whole['card_bytes'])


if __name__ == '__main__':
    unittest.main()
