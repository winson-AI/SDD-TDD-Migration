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
            self.assertLess(len(json.dumps(line, ensure_ascii=False, separators=(',', ':'))), 400)  # what the host reads per step
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


class ReadyImplementerTests(unittest.TestCase):
    def test_resource_sync_is_delivered_after_independent_dispatch_and_conflicts_are_local(self):
        from unittest.mock import patch
        import ledger
        import resource_binding
        from test_iterative_spec import UpstreamPlanTests

        fixture = UpstreamPlanTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        f = fixture.f
        fixture.freeze(fixture.t.plan('M001'))
        fixture.t.freeze('M002')
        f.call('assign', {'role': 'implementer', 'assignment_id': 'sibling', 'instance_id': 'coder'}, module='M002')

        replay = ledger.read_events

        def one_slot(*args, **kwargs):
            state, events = replay(*args, **kwargs)
            state['max_parallel_modules'] = 1
            return state, events

        with patch.object(ledger, 'read_events', side_effect=one_slot), \
                patch.object(resource_binding, 'needs_sync', side_effect=lambda m, a: m['module_id'] == 'M001'), \
                patch.object(resource_binding, 'sync') as sync, \
                patch.object(ledger, 'project_outcome', wraps=ledger.project_outcome) as project:
            lines = drive.drive(f.root, MO)
            sync.assert_not_called()
            project.assert_called_once()
            pending = next(line for line in lines if line.get('operation') == 'resource-sync')
            self.assertEqual(pending['module_id'], 'M001')
            sibling = next(line for line in lines if line['kind'] == 'running' and line.get('role') == 'implementer'
                           and line.get('module_id') == 'M002')
            self.assertLess(lines.index(sibling), lines.index(pending))
            self.assertFalse(any(line['kind'] == 'running' and line.get('module_id') == 'M001' for line in lines))
            assignment = f.state()['modules']['M001']['assignments'][pending['assignment_id']]
            parent, prefix, _ = resource_binding.attempts(f.root, assignment)
            out = parent / prefix
            out.mkdir(parents=True)
            (out / 'receipt.json').write_text(json.dumps({'status': 'rejected', 'reason': 'target file already differs'}))
            lines = drive.drive(f.root, MO)
            conflict = next(line for line in lines if line.get('reason') == 'resource-sync-conflict')
            self.assertEqual(conflict['module_id'], 'M001')
            self.assertTrue(any(line['kind'] == 'running' and line.get('module_id') == 'M002' for line in lines))
            proof = f.ref('mock-resource-sync.json', {'status': 'SYNCED'})
            with patch.object(resource_binding, 'ready_receipt', return_value={'receipt_ref': proof, 'result_ref': proof}):
                self.assertFalse(any(line['kind'] == 'running' and line.get('module_id') == 'M001'
                                     for line in drive.drive(f.root, MO)))
                sibling_id = sibling['assignment_id']
                f.call('revoke', {'assignment_id': sibling_id, 'stopped_worker_ref': proof}, role='host', module='M002')
                f.call('suspend', {'kind': 'tooling', 'reason': 'sibling paused', 'root_cause': 'stopped', 'owner': 'host'},
                       module='M002')
                lines = drive.drive(f.root, MO)
                self.assertTrue(any(line['kind'] == 'running' and line.get('module_id') == 'M001' for line in lines))
                self.assertFalse(f.state()['modules']['M001']['assignments'][pending['assignment_id']]['resource_wait'])
                self.assertEqual(sum(e['operation'] == 'resource-start' for e in replay(f.root)[1]), 1)

    def test_resource_receipt_wakes_a_waiter_without_a_journal_event(self):
        from unittest.mock import patch

        from tempfile import TemporaryDirectory
        import resource_binding
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'reports').mkdir()
        conflict = [{'kind': 'signal', 'reason': 'resource-sync-conflict'}]
        resumed = [{'kind': 'running', 'module_id': 'M001'}]
        with patch.object(drive, 'journal_size', return_value=40), \
                patch.object(drive, 'tick', side_effect=[(conflict, 8, 0), (resumed, 8, 0)]), \
                patch.object(drive, 'unseen', side_effect=lambda root, lines: (lines, 0)), \
                patch.object(drive.time, 'sleep', side_effect=lambda _: resource_binding.notify_ready(self.root, {'receipt_ref': {'sha256': 'receipt'}})):
            self.assertEqual(drive.drive(self.root, MO, wait=10)[0], resumed[0])

    def test_independent_implementer_reaches_host_before_existing_frozen_commands(self):
        from unittest.mock import patch
        import ledger
        from test_iterative_spec import UpstreamPlanTests
        from test_run_rehearsal import RunWalk

        fixture = UpstreamPlanTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        f = fixture.f
        plan = fixture.t.plan('M001')
        next(p for p in plan['paths'] if p['kind'] == 'build')['command']['argv'][-1] = 'pass # independent build unit'
        fixture.freeze(plan)
        fixture.t.freeze('M002')
        f.call('assign', {'role': 'implementer', 'assignment_id': 'I1', 'instance_id': 'coder'}, module='M001')
        walk = RunWalk(); walk.f = f; walk.t = fixture.t
        step = next(step for step in f.state()['next_steps'] if step['module_id'] == 'M001')
        walk.model_turn(step)
        f.call('accept', {'assignment_id': 'I1'}, module='M001')
        with patch.object(ledger, 'frozen_tests', wraps=ledger.frozen_tests) as frozen_tests:
            lines = drive.drive(f.root, MO, wait=1)
            self.assertTrue(any(line['kind'] == 'running' and line.get('role') == 'implementer'
                                and line.get('module_id') == 'M002' for line in lines))
            frozen_tests.assert_not_called()
            self.assertEqual(f.state()['modules']['M001']['results'], {})
            drive.drive(f.root, MO)
            frozen_tests.assert_called()
            self.assertEqual(f.state()['modules']['M001']['results']['M001-B']['quality'], 'green-passed')


class MechanicalHandoffTests(unittest.TestCase):
    def setUp(self):
        import ledger
        from test_iterative_spec import UpstreamPlanTests
        from test_run_rehearsal import RunWalk

        self.fixture = fixture = UpstreamPlanTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.f = f = fixture.f
        fixture.freeze(fixture.t.plan('M001'))
        f.call('assign', {'role': 'implementer', 'assignment_id': 'I1', 'instance_id': 'coder'}, module='M001')
        walk = RunWalk(); walk.f = f; walk.t = fixture.t
        walk.model_turn(next(step for step in f.state()['next_steps'] if step['module_id'] == 'M001'))
        f.call('accept', {'assignment_id': 'I1'}, module='M001')
        ledger.advance(f.root, MO, 'M001', defer_commands=True)
        self.assignment = next(a for a in f.state()['modules']['M001']['assignments'].values() if not a['closed'])

    def test_ready_fixer_is_returned_before_the_independent_build(self):
        from unittest.mock import patch
        import ledger

        f = self.f
        original_plan = self.fixture.t.plan

        def plan_with_failing_unit(mid):
            plan = original_plan(mid)
            next(p for p in plan['paths'] if p['kind'] == 'build')['command']['argv'][-1] = 'pass # separate build unit'
            next(p for p in plan['paths'] if p['kind'] == 'unit')['command']['argv'][-1] = 'raise SystemExit(1)'
            return plan

        with patch.object(self.fixture.t, 'plan', side_effect=plan_with_failing_unit):
            self.fixture.t.freeze('M002')
        f.call('assign', {'role': 'implementer', 'assignment_id': 'I2', 'instance_id': 'coder2'}, module='M002')
        from test_run_rehearsal import RunWalk
        walk = RunWalk(); walk.f = f; walk.t = self.fixture.t
        walk.model_turn(next(step for step in f.state()['next_steps'] if step['module_id'] == 'M002'))
        f.call('accept', {'assignment_id': 'I2'}, module='M002')
        ledger.advance(f.root, MO, 'M002', defer_commands=True)
        state, _ = ledger.read_events(f.root)
        assignment = next(a for a in state['modules']['M002']['assignments'].values() if not a['closed'])
        submission = ledger.frozen_tests(f.root, state, 'M002', assignment['assignment_id'])
        f.raw('submit', submission, role='test-runner', instance=assignment['instance_id'], module='M002')
        with patch.object(ledger, 'frozen_tests', wraps=ledger.frozen_tests) as run:
            lines = drive.drive(f.root, MO)
            self.assertTrue(any(row['kind'] == 'running' and row.get('role') == 'fixer'
                                and row.get('module_id') == 'M002' for row in lines))
            self.assertEqual(f.state()['modules']['M002']['results']['M002-U']['quality'], 'red-bug')
            run.assert_not_called()
            drive.drive(f.root, MO)
            run.assert_called_once()

    def test_ready_plan_is_delivered_once_before_the_pending_build(self):
        from unittest.mock import patch
        import ledger

        with patch.object(ledger, 'frozen_tests', wraps=ledger.frozen_tests) as run:
            lines = drive.drive(self.f.root, MO)
            self.assertTrue(any(row['kind'] == 'dispatch' and row['operation'] == 'plan'
                                and row.get('module_id') == 'M002' for row in lines))
            run.assert_not_called()
            drive.drive(self.f.root, MO)
            run.assert_called_once()
        self.assertEqual(self.f.state()['modules']['M001']['results']['M001-B']['quality'], 'green-passed')

    def test_ready_coding_rotation_is_delivered_once_before_the_pending_build(self):
        from unittest.mock import patch
        import ledger

        f = self.f
        fixture = self.fixture
        original = fixture.t.plan

        def separate_plan(mid):
            plan = original(mid)
            next(p for p in plan['paths'] if p['kind'] == 'build')['command']['argv'][-1] = 'pass # separate build unit'
            return plan

        with patch.object(fixture.t, 'plan', side_effect=separate_plan):
            fixture.t.freeze('M002')
        f.call('session', {'role': 'implementer', 'session_id': 'S-OLD'}, module='M002')
        before = f.state()
        step = next(step for step in before['next_steps'] if step['module_id'] == 'M002')
        f.call('session', request={'schema_version': 1, 'request_id': 'large-input-m2', 'run_id': before['run_id'],
            'module_id': 'M002', 'expected_revision': step['expected_revision'], 'operation': 'session',
            'payload': {'role': 'implementer', 'session_id': 'S-OLD'},
            'hint': {'session_id': 'S-OLD', 'card_sha256': step['card_sha256'],
                     'context_inputs': [{'kind': 'log', 'ref': f.ref('large-m2.log', 'x'*100001)}]}})
        with patch.object(ledger, 'frozen_tests', wraps=ledger.frozen_tests) as run:
            lines = drive.drive(f.root, MO)
            self.assertTrue(any(row['kind'] == 'rotate' and row['module_id'] == 'M002' for row in lines))
            run.assert_not_called()
            drive.drive(f.root, MO)
            run.assert_called_once()

    def test_finished_build_prefix_is_resumed_without_repeating_a_command(self):
        from unittest.mock import patch
        import ledger
        import execute_test
        from contracts import check_ref, read_json

        f = self.f; aid = self.assignment['assignment_id']
        output = f.root / 'runs/build' / aid / 'M001-B'
        build_ref = execute_test.execute(f.root, 'M001', aid, 'M001-B', output=output)
        initial = read_json(check_ref(build_ref))['test_run_id']
        state, _ = ledger.read_events(f.root)
        with patch.object(execute_test.subprocess, 'Popen', wraps=execute_test.subprocess.Popen) as run:
            ledger.frozen_tests(f.root, state, 'M001', aid)  # unit runs, then the host stops before submit
            self.assertEqual(run.call_count, 1)
            run.reset_mock()
            ledger.advance(f.root, MO, 'M001')
            run.assert_not_called()
        rows = f.state()['modules']['M001']['results']
        self.assertEqual((rows['M001-B']['test_run_id'], rows['M001-B']['execution_receipt']), (initial, build_ref))
        self.assertEqual(rows['M001-U']['quality'], 'green-passed')

    def test_wrong_fence_and_incomplete_output_are_never_replayed(self):
        import ledger
        import execute_test
        from contracts import Rejected, check_ref, read_json

        f = self.f; aid = self.assignment['assignment_id']
        output = f.root / 'runs/build' / aid / 'M001-B'
        output.mkdir(parents=True)
        state, _ = ledger.read_events(f.root)
        with self.assertRaisesRegex(Rejected, 'incomplete execution output'):
            ledger.frozen_tests(f.root, state, 'M001', aid)
        output.rmdir()
        ref = execute_test.execute(f.root, 'M001', aid, 'M001-B', output=output)
        receipt = read_json(check_ref(ref)); receipt['fencing_token'] -= 1
        ledger.atomic(Path(ref['path']), receipt)
        with self.assertRaisesRegex(Rejected, 'fencing token'):
            ledger.frozen_tests(f.root, state, 'M001', aid)
        self.assertFalse(f.state()['modules']['M001']['results'])


class CursorCoverageTests(unittest.TestCase):
    def setUp(self):
        import test_ledger
        self.f = f = test_ledger.FlowTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()

    def test_a_decision_only_a_person_gives_comes_with_what_is_asked(self):
        f = self.f
        f.call('suspend', {'kind': 'human', 'reason': 'which retry limit does the old client keep?', 'owner': 'human',
                           'root_cause': {'category': 'spec', 'summary': 'retry limit unstated', 'confidence': 'confirmed', 'owner': 'human', 'next_action': 'ask'}})
        person = next(line for line in drive.drive(f.root, MO) if line['kind'] == 'person')
        self.assertEqual((person['module_id'], person['operation'], person['reason']), ('M001', 'resume', 'human-decision-required'))
        self.assertTrue(person['approval_subject_sha256'])

    def test_a_refused_request_reaches_the_host_as_a_signal(self):
        import progress_signals
        drive.drive(self.f.root, MO)  # the coder is dispatched: nothing moves until it submits
        progress_signals.record_rejection(self.f.root, {'operation': 'accept', 'module_id': 'M001'}, {'role': 'module-orchestrator', 'instance_id': 'mo'},
                                          'unit tests must pass before the static review')
        lines = drive.drive(self.f.root, MO)
        signal = next(line for line in lines if line['kind'] == 'signal' and line['reason'] == 'operation-rejected')
        self.assertEqual((signal['module_id'], signal['severity']), ('M001', 'action'))
        self.assertTrue(any(line['reason'] == 'attention-report' for line in lines if line['kind'] == 'signal'))
        self.assertLess(max(len(json.dumps(line, ensure_ascii=False)) for line in lines), 600)  # no evidence dumps
        again = drive.drive(self.f.root, MO)  # a standing signal is printed once: later ticks count it
        self.assertEqual([line['kind'] for line in again if line['kind'] == 'signal'], [])
        self.assertEqual(again[-1]['signals_held'], len([line for line in lines if line['kind'] == 'signal' and line['reason'] != 'attention-report']))


class SessionReuseTests(unittest.TestCase):
    def test_the_fixer_line_names_the_implementer_session_to_resume_and_its_instance(self):
        import test_ledger
        f = test_ledger.FlowTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        f.call('session', {'role': 'implementer', 'session_id': 'S-IMP'})
        f.implementation()
        a, result = f.make_test_result(quality='red-bug')
        result['paths'][0]['root_cause']['confidence'] = 'confirmed'
        f.submit(result, a)
        lines = drive.drive(f.root, MO)
        fixer = next(line for line in lines if line.get('role') == 'fixer')
        self.assertEqual((fixer['kind'], fixer['session_id'], fixer['session_affinity']), ('running', 'S-IMP', 'implementer'))
        self.assertEqual(fixer['instance_id'], f.state()['modules']['M001']['assignments'][fixer['assignment_id']]['instance_id'])
        self.assertTrue(Path(fixer['card']).is_file() and fixer['card_bytes'] > 0)


    def test_drive_rotates_before_assigning_and_resumes_the_same_frozen_work(self):
        import test_ledger
        f = test_ledger.FlowTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        f.call('session', {'role': 'implementer', 'session_id': 'S-OLD'})
        before = f.state(); step = before['next_steps'][0]
        f.call('session', request={'schema_version': 1, 'request_id': 'large-input', 'run_id': before['run_id'],
            'module_id': 'M001', 'expected_revision': before['modules']['M001']['revision'], 'operation': 'session',
            'payload': {'role': 'implementer', 'session_id': 'S-OLD'},
            'hint': {'session_id': 'S-OLD', 'card_sha256': step['card_sha256'],
                     'context_inputs': [{'kind': 'log', 'ref': f.ref('large.log', 'x'*100001)}]}})
        rotation = drive.drive(f.root, MO)[0]
        self.assertEqual((rotation['kind'], rotation['role'], rotation['model_tier']), ('rotate', 'implementer', 'strong'))
        self.assertNotIn('card', rotation)
        self.assertEqual((rotation['run_id'], rotation['module_id']), (before['run_id'], 'M001'))
        self.assertFalse(f.state()['modules']['M001']['assignments'])
        checkpoint = rotation['session_rotate']['checkpoint']
        f.call('session', {'role': checkpoint['role'], 'session_id': 'S-NEW', 'reason': 'context-rotation',
                           'checkpoint_ref': f.ref('checkpoint.json', checkpoint)})
        line = drive.drive(f.root, MO)[0]
        self.assertEqual((line['kind'], line['session_id']), ('running', 'S-NEW'))
        self.assertNotIn('resumed_from_bytes', line)
        self.assertEqual(f.state()['modules']['M001']['freeze_id'], before['modules']['M001']['freeze_id'])

    def test_reasoning_rules_are_offered_on_demand_and_never_in_the_resident_card(self):
        import reading
        step = {'role': 'diagnostician', 'operation': 'diagnose'}
        module = {'results': {'P1': {'quality': 'yellow-blocked', 'root_cause': {'confidence': 'suspected'}}}}
        topics = {(row['ref'], row['section']) for row in reading.on_demand({}, module, step)}
        resident = {(row['ref'], row['section']) for row in reading.card({}, module, step)}
        extra = set(reading.reasoning_sections(module))
        self.assertTrue(extra and extra <= topics and extra.isdisjoint(resident))

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
