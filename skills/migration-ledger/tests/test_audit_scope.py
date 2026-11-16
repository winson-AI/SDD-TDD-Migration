"""Empty init paths remain recoverable; audit execution excludes valid Green paths."""
import test_ledger
import copy
import unittest

import test_context_readiness
import test_audit_closure
import ledger
from contracts import Rejected, validate_result


class AuditScopeTests(unittest.TestCase):
    def fixture(self, kind=test_context_readiness.ContextReadinessTests):
        f = kind()
        call = f.call
        def empty_global(op, payload=None, **kwargs):
            if op == 'init':
                payload = {**payload, 'global_paths': []}
            return call(op, payload, **kwargs)
        f.call = empty_global
        f.setUp(); self.addCleanup(f.doCleanups)
        return f

    def review(self, f):
        test_ledger.code_review(f)
        f.call('audit-assign', {'assignment_id': 'REVIEW', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        s = f.state(); scope = ledger.audit_scope(s)
        return {'schema_version': 1, 'kind': 'audit-review', 'run_id': 'demo', 'module_id': 'GLOBAL',
                'assignment_id': 'REVIEW', 'actor_instance_id': 'auditor', 'freeze_id': scope['freeze_id'],
                'code_baseline': scope['code_baseline'], 'snapshot': s['audit_assignment']['snapshot'],
                'paths': [], 'execution_status': 'no-retest-needed',
                'review_ref': f.ref('review.md', 'Read all module evidence: no unresolved cases; no tests rerun.')}

    def test_empty_init_recovers_to_independent_review_without_automation_environment(self):
        f = self.fixture(); f.completed(); test_ledger.code_review(f)
        s = f.state(); original = copy.deepcopy(s['modules']['M001']['results'])
        self.assertEqual(s['global_paths'], [])
        self.assertEqual(s['global_next_step']['operation'], 'audit-assign')
        self.assertEqual(s['global_next_step']['context_gate']['stage'], 'audit-verdict')
        self.assertEqual(s['global_next_step']['path_ids'], [])
        report = self.review(f)
        missing = copy.deepcopy(report); missing.pop('review_ref')
        with self.assertRaises(Rejected):
            f.raw('audit', {'report_ref': f.ref('missing-review.json', missing)}, role='auditor', module=None)
        f.raw('audit', {'report_ref': f.ref('review.json', report)}, role='auditor', module=None)
        s = f.state()
        self.assertEqual(s['quality'], 'green-passed')
        self.assertEqual(s['audit']['execution_status'], 'no-retest-needed')
        self.assertEqual(s['modules']['M001']['results'], original)
        self.assertEqual(s['global_next_step']['reason'], 'await-delivery-authorization')

    def test_final_audit_preserves_ready_path_evidence_until_a_blocked_peer_recovers(self):
        import sys
        from unittest.mock import patch
        import audit_execution
        import execute_test
        from contracts import check_ref, read_json

        f = test_context_readiness.ContextReadinessTests()
        original = f.call

        def initialize(op, payload=None, **kwargs):
            if op == 'init':
                fixture = f.ref('global-runner.py', '''import json
import sys
with open(sys.argv[sys.argv.index('--result-file') + 1], 'w') as target:
    json.dump({'assertions': [{'assertion_id': 'A1', 'expected': 2, 'actual': 2, 'passed': True}]}, target)
''')
                command = {'argv': [sys.executable, fixture['path']], 'cwd': str(f.target)}
                web = {**payload['global_paths'][0], 'path_id': 'WEB', 'kind': 'automation', 'platform': 'web'}
                payload = {**payload, 'test_adapter': {'device': {'platforms': ['web'], 'web': {'url': 'https://example.test'}}},
                           'global_paths': [{**web, 'path_id': 'READY', 'platform': 'host', 'command': command}, web]}
            return original(op, payload, **kwargs)

        f.call = initialize
        f.setUp(); self.addCleanup(f.doCleanups)
        f.completed()
        test_ledger.code_review(f)
        state = f.state()
        archived = check_ref(state['target_preview']['web_main_config'])
        contents = archived.read_bytes()
        mo = {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}
        ledger.advance_run(f.root, mo, yield_after_test=True)
        state = f.state()
        self.assertEqual(state['audit_test_assignment']['path_ids'], ['READY'])
        self.assertTrue(state['audit_test_assignment']['closed'])
        self.assertEqual((state['global_next_step']['operation'], state['global_next_step']['path_ids']), ('audit-test-assign', ['WEB']))
        archived.unlink()  # The Web configuration disappears after the other batch is already accepted.
        state = f.state()
        self.assertEqual(state['audit_assignment']['path_ids'], ['READY', 'WEB'])
        self.assertEqual(state['global_next_step']['reason'], 'audit-path-inputs-unavailable')
        self.assertEqual(set(state['global_next_step']['audit_blocked_paths']), {'WEB'})
        refs, rows = audit_execution.evidence(state)
        self.assertEqual([(row['path_id'], row['quality']) for row in rows], [('READY', 'green-passed')])
        with self.assertRaisesRegex(Rejected, 'every required PATH'):
            audit_execution.evidence(state, ledger.audit_scope(state), {'paths': rows, 'test_result_ref': refs[0]})
        archived.write_bytes(contents)
        command = state['global_paths'][0]['command']
        with patch.object(execute_test, 'builtin_main', return_value={'argv': command['argv']}):
            ledger.advance_run(f.root, mo)
        state = f.state()
        self.assertEqual(state['quality'], 'green-passed')
        self.assertEqual(state['audit_results']['READY']['test_run_id'], rows[0]['test_run_id'])
        report = read_json(check_ref(state['audit']['report_ref']))
        self.assertEqual(report['test_result_refs'][0], refs[0])
        self.assertEqual([row['path_id'] for row in report['paths']], ['READY', 'WEB'])

    def test_frozen_leaf_path_runs_before_manual_global_path(self):
        import sys
        import test_split_testing
        from contracts import check_ref, read_json
        from execute_test import execute
        from harmony_stage import build

        fixture = test_split_testing.SplitTestingTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        f = fixture.f
        script = f.ref('audit-driver.py', '''import json
import sys
with open(sys.argv[sys.argv.index('--result-file') + 1], 'w') as target:
    json.dump({'assertions': [{'assertion_id': 'A1', 'expected': 2, 'actual': 2, 'passed': True}]}, target)
''')
        plan = f.plan

        def with_command():
            draft = plan()
            draft['paths'][0]['command'] = {'argv': [sys.executable, script['path']], 'cwd': str(f.target)}
            return draft

        f.plan = with_command
        fixture.prepare(); fixture.compile(); fixture.defer()
        test_ledger.code_review(f)
        actor = {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}
        ledger.advance_run(f.root, actor, defer_commands=True)
        state = ledger.status(f.root, view='step')
        self.assertEqual([path['path_id'] for path in state['audit_input']['paths']], ['P1'])
        task = f.state()['audit_test_assignment']
        self.assertEqual(task['path_ids'], ['P1'])
        self.assertTrue(f.state()['global_next_step']['mechanical'])

        ledger.advance_run(f.root, actor)
        state = f.state()
        first, manual = state['audit_test_history'][-1], state['audit_test_assignment']
        self.assertEqual(first['path_ids'], ['P1'])
        self.assertEqual(set(read_json(check_ref(first['context_ref']))['execution']['commands']), {'P1'})
        self.assertEqual(manual['path_ids'], ['GP1'])
        self.assertFalse(state['global_next_step']['mechanical'])
        self.assertNotEqual(manual['instance_id'], state['audit_assignment']['instance_id'])
        f.test_argv = [sys.executable, script['path']]
        f.record(f.report('audit-execution', module=None, instance=manual['instance_id']))
        aid = manual['assignment_id']
        receipt = execute(f.root, 'GLOBAL', aid, 'GP1', f.test_argv, str(f.target), f.base / 'manual-audit')
        f.raw('audit-test-submit', {'result_ref': f.ref('manual-audit.json', build(f.root, 'GLOBAL', aid, [receipt]))},
              role='test-runner', instance=manual['instance_id'], module=None)
        ledger.advance_run(f.root, actor)
        self.assertEqual([(row['path_id'], row['quality']) for row in f.state()['audit']['paths']],
                         [('P1', 'green-passed'), ('GP1', 'green-passed')])

    def test_unstarted_runner_returns_only_the_reported_paths(self):
        import sys
        from execute_test import execute
        from harmony_stage import build

        f = test_context_readiness.ContextReadinessTests()
        call = f.call

        def initialize(op, payload=None, **kwargs):
            if op == 'init':
                original = payload['global_paths'][0]
                payload = {**payload, 'global_paths': [{**original, 'path_id': pid} for pid in ('MISSING', 'PEER')]}
            return call(op, payload, **kwargs)

        f.call = initialize
        f.setUp(); self.addCleanup(f.doCleanups)
        f.completed(); test_ledger.code_review(f)
        f.call('audit-assign', {'assignment_id': 'AUDIT', 'instance_id': 'auditor'}, role='global-orchestrator', module=None)
        f.raw('audit-test-assign', {'assignment_id': 'FIRST', 'instance_id': 'runner', 'path_ids': ['MISSING', 'PEER']},
              role='global-orchestrator', module=None)
        step = ledger.status(f.root, view='step')
        self.assertEqual(step['request']['operation'], 'context-submit')
        self.assertEqual(step['context']['stage'], 'audit-execution')
        blocked = f.report('audit-execution', module=None, instance='runner', blocked='test-environment')
        issue = blocked['checks']['test-environment']
        issue['path_ids'] = ['FOREIGN']
        with self.assertRaisesRegex(Rejected, 'within its assignment'):
            f.record(blocked)
        issue['path_ids'] = ['MISSING']
        gap = f.record(blocked)
        state = f.state()
        self.assertTrue(state['audit_test_assignment']['closed'])
        self.assertEqual(state['global_next_step']['path_ids'], ['PEER'])
        self.assertEqual(set(state['global_next_step']['audit_blocked_paths']), {'MISSING'})

        f.raw('audit-test-assign', {'assignment_id': 'SECOND', 'instance_id': 'runner', 'path_ids': ['PEER']},
              role='global-orchestrator', module=None)
        script = f.ref('peer-driver.py', '''import json
import sys
with open(sys.argv[sys.argv.index('--result-file') + 1], 'w') as target:
    json.dump({'assertions': [{'assertion_id': 'A1', 'expected': 2, 'actual': 2, 'passed': True}]}, target)
''')
        f.test_argv = [sys.executable, script['path']]
        f.record(f.report('audit-execution', module=None, instance='runner'))
        late_gap = f.report('audit-execution', module=None, instance='runner', blocked='test-environment')
        f.record(late_gap)
        self.assertFalse(f.state()['audit_test_assignment']['closed'])  # An authorized runner still holds its assignment.
        f.record(f.report('audit-execution', module=None, instance='runner'))
        receipt = execute(f.root, 'GLOBAL', 'SECOND', 'PEER', f.test_argv, str(f.target), f.base / 'peer-audit')
        f.raw('audit-test-submit', {'result_ref': f.ref('peer-audit.json', build(f.root, 'GLOBAL', 'SECOND', [receipt]))},
              role='test-runner', instance='runner', module=None)
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-unavailable')

        auditor_report = f.record(f.report('audit-testing', module=None, instance='auditor', blocked='test-environment'))
        f.raw('audit-unavailable', {'context_ref': auditor_report}, role='auditor', module=None)
        paused = f.state()
        self.assertTrue(paused['audit_assignment']['closed'])
        self.assertEqual(paused['audit']['deferred_path_ids'], ['MISSING'])
        self.assertEqual(paused['global_next_step']['reason'], 'audit-path-inputs-unavailable')
        omission = next(row for row in paused['audit']['paths'] if row['path_id'] == 'MISSING')
        self.assertFalse(omission['executed'])
        self.assertIn(gap, omission['root_cause']['evidence_refs'])
        ready = f.record(f.report('audit-testing', module=None, instance='auditor'))
        self.assertEqual(f.state()['global_next_step']['reason'], 'automation-environment-restored')
        f.raw('audit-assign', {'assignment_id': 'RESTORED', 'instance_id': 'auditor', 'context_ref': ready},
              role='global-orchestrator', module=None)
        self.assertNotIn('deferred_preflight_blocks', f.state()['audit'])

    def test_builtin_web_receipt_fingerprint_ignores_unbound_native_artifacts(self):
        import audit_execution

        f = self.fixture(); f.completed()
        s = f.state()
        config = f.ref('web-execution.json', {'headless': True})
        web = {'path_id': 'WEB', 'kind': 'automation', 'platform': 'web'}
        s['global_paths'] = [web]
        s['target_preview'] = {'web_main_config': config}
        s['test_adapter'] = {'device': {'platforms': ['web'], 'web': {'url': 'https://example.test'}}}
        original = ledger.audit_scope(s)
        stamp = audit_execution.input_fingerprint(s, original, web, f.root)
        legacy = audit_execution.input_fingerprint(s, original, web, f.root, version=1)
        self.assertIsNotNone(stamp)
        self.assertIsNotNone(legacy)
        s['modules']['M001']['build_artifacts'] = [f.ref('native.hap', 'Unrelated build output')]
        current = ledger.audit_scope(s)
        self.assertEqual(audit_execution.input_fingerprint(s, current, web, f.root), stamp)
        self.assertNotEqual(audit_execution.input_fingerprint(s, current, web, f.root, version=1), legacy)
        s['target_preview']['web_main_config'] = f.ref('new-web.json', {'headless': False})
        self.assertNotEqual(audit_execution.input_fingerprint(s, current, web, f.root), stamp)

    def test_empty_global_does_not_block_cross_module_repair_and_retest(self):
        f = self.fixture(test_audit_closure.ClosureTests)
        f.test_cross_module_fix_then_owner_and_source_verification()
        s = f.state()
        self.assertEqual(s['global_paths'], [])
        self.assertTrue(s['global_next_step']['ready'])
        self.assertEqual(ledger.audit_scope(s)['plan']['paths'], [])
        report = self.review(f)
        f.call('audit', {'report_ref': f.ref('review.json', report)}, role='auditor', module=None)
        self.assertEqual(f.state()['quality'], 'green-passed')

    def test_selector_keeps_red_yellow_and_excludes_green_and_review_cannot_hide_them(self):
        f = self.fixture(); f.completed(); s = f.state()
        m = s['modules']['M001']; original = m['plan']['paths'][0]
        for pid, quality in [('RED', 'red-bug'), ('YELLOW', 'yellow-blocked')]:
            m['plan']['paths'].append({**original, 'path_id': pid})
            m['results'][pid] = {'path_id': pid, 'quality': quality, 'test_run_id': pid}
        scope = ledger.audit_scope(s)
        self.assertEqual([p['path_id'] for p in scope['plan']['paths']], ['RED', 'YELLOW'])
        report = self.review(f)
        assignment = f.state()['audit_assignment']
        with self.assertRaisesRegex(Rejected, 'review cannot skip'):
            validate_result(report, scope, assignment)

    def test_empty_global_failed_repair_still_requires_human(self):
        f = self.fixture(test_audit_closure.ClosureTests)
        f.test_failed_consumer_verification_stops_for_human()
        self.assertEqual(f.state()['global_paths'], [])

    def test_optional_global_green_is_reused_until_its_baseline_changes(self):
        f = self.fixture(); f.completed(); s = f.state()
        base = ledger.audit_scope(s)['code_baseline']
        s['global_paths'] = [{**s['modules']['M001']['plan']['paths'][0], 'path_id': 'GP1'}]
        s['audit_results'] = {'GP1': {'quality': 'green-passed', 'test_run_id': 'prior-global', 'code_baseline': base}}
        self.assertEqual(ledger.audit_scope(s)['plan']['paths'], [])
        s['audit_results']['GP1']['code_baseline'] = 'previous-code'
        scope = ledger.audit_scope(s)
        self.assertEqual([p['path_id'] for p in scope['plan']['paths']], ['GP1'])
        self.assertTrue(scope['stale'])  # Expired Green must also link retest_of.

    def test_changed_global_acceptance_requires_retest_even_with_identical_code(self):
        import run_changes
        f = self.fixture(); f.completed(); s = f.state()
        base = ledger.audit_scope(s)['code_baseline']
        path = {**s['modules']['M001']['plan']['paths'][0], 'path_id': 'GP1'}
        s['global_paths'] = [path]
        s['audit_results'] = {'GP1': {'quality': 'green-passed', 'executed': True,
            'test_run_id': 'prior-global', 'code_baseline': base}}
        updated = copy.deepcopy(path); updated['expected_assertions'][0]['expected'] = 'corrected acceptance'
        report = {'schema_version': 1, 'run_id': 'demo', 'reason': 'Correct GLOBAL acceptance',
            'boundary_review': {'semantic_change': True, 'authorization_change': False, 'unresolved_questions': [],
                'reason': 'Reviewed integration acceptance correction', 'evidence_refs': [f.ref('boundary.md', 'Only integration expectation changed')]},
            'context_patch': {}, 'root_updates': [], 'global_spec_ref': f.ref('corrected-global.md', 'Revised GLOBAL expectation'),
            'contract_patch': {'global_paths': [updated]}, 'modules': [{'module_id': 'M001', 'action': 'unchanged',
                'reason': 'Module implementation contract unchanged', 'evidence_refs': [f.ref('impact.md', 'Only integration expectation changed')],
                'resume_blocker_sha256': None}]}
        run_changes.handle(f.root.resolve(), s, {'operation': 'run-review', 'payload': {'report_ref': f.ref('global-revision.json', report)}},
                           {'role': 'global-orchestrator', 'instance_id': 'go'})
        subject = s['run_change_review']['subject_sha256']
        s['decisions']['REV'] = {'decision': 'approved', 'module_id': None, 'consumed': False,
            'subject_sha256': subject, 'human_source_ref': f.ref('approve-global.md', 'Approve corrected acceptance')}
        run_changes.handle(f.root.resolve(), s, {'operation': 'revise-run', 'payload': {'decision_id': 'REV', 'subject_sha256': subject}},
                           {'role': 'host', 'instance_id': 'host'})
        scope = ledger.audit_scope(s)
        self.assertEqual(scope['code_baseline'], base)
        self.assertEqual(scope['plan']['paths'], [updated])
        self.assertTrue(scope['stale'])
        self.assertEqual(scope['results']['GP1']['test_run_id'], 'prior-global')
        self.assertTrue(scope['results']['GP1']['stale'])
        self.assertEqual(s['modules']['M001']['phase'], 'completed')
