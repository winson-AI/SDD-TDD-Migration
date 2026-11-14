"""Wave scheduling, input-bound reuse, and stale worker recovery."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import integration
import ledger
import test_audit_closure
from contracts import Rejected, check_ref, digest, file_ref
from execute_test import execute


class WaveIntegrationTests(unittest.TestCase):
    def setUp(self):
        f = self.f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state(); f.root = f.base / 'wave'
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'global_spec', 'new_architecture')},
                        'dimension_slicing_required': False, 'split_testing_required': False, 'context_readiness_required': False,
                        'case_ids': ['C1', 'C2'], 'requirement_ids': ['R1'], 'max_fix_rounds': 1,
                        'global_paths': [{'path_id': 'GP1', 'case_id': 'C1', 'expected_assertions': [{'assertion_id': 'A1', 'expected': 2}]}]}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm1')]}, role='global-orchestrator', module=None)
        f.call('register', {'module_id': 'M002', 'case_ids': ['C2'], 'dependencies': ['M001'], 'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        f.global_plan(case_owners={'C1': ['M001', 'GLOBAL'], 'C2': ['M002']}, requirement_owners={'R1': ['M001', 'M002']})
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer'); f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})

    def first_wave(self):
        f = self.f
        f.implement('M001', 'I1'); f.verify_module('M001', 'T1'); f.complete('M001')
        return f.state()['global_next_step']

    def test_missing_web_config_does_not_block_the_ready_android_path(self):
        from unittest.mock import patch
        import progress_signals

        f = self.f
        self.first_wave()
        s = ledger.read_events(f.root)[0]
        s['test_adapter'] = {'device': {'platforms': ['web', 'android'], 'web': {'url': 'https://example.test'},
                                       'android': {'serial': 'test'}}}
        web = {**s['global_paths'][0], 'path_id': 'WEB', 'platform': 'web', 'kind': 'automation'}
        android = {**web, 'path_id': 'ANDROID', 'platform': 'android'}
        s['global_paths'] = [web, android]
        archived = f.ref('archived-web.json', {'headless': True})
        s['target_preview'] = {'web_main_config': archived}
        check_ref(archived).unlink()
        step = ledger.routing(s)['global_next_step']
        self.assertEqual(step['path_ids'], ['ANDROID'])
        self.assertEqual(set(step['integration_blocked_paths']), {'WEB'})
        payload = {'assignment_id': 'INT', 'instance_id': 'wave-runner', 'path_ids': step['path_ids']}
        integration.handle(s, {'operation': 'integration-assign', 'payload': payload},
                           {'role': 'global-orchestrator', 'instance_id': 'go'}, 99)
        self.assertEqual([path['path_id'] for path in integration.scope(s)['plan']['paths']], ['ANDROID'])
        # The drive loop mechanically assigns the wave before publishing its host signals.
        running = ledger.routing(s)['global_next_step']
        self.assertEqual(running['operation'], 'integration-submit')
        signals = progress_signals.build(f.root, s, [], [], running)['signals']
        self.assertTrue(any(signal['reason'] == 'integration-path-inputs-unavailable' and signal['evidence']['path_id'] == 'WEB'
                            for signal in signals))
        s['integration_assignment']['closed'] = True
        self.assertIn('WEB', [path['path_id'] for path in ledger.audit_scope(s)['plan']['paths']])
        with patch.object(ledger, 'global_baseline', side_effect=Rejected('shared code drift')):
            self.assertEqual(integration.due(s), [])

    def run_gp1(self, aid, passing=True):
        f = self.f; scope = integration.scope(f.state())
        adapter = f.base / f'wave-{aid}.py'
        adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n"
                           "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':%d,'passed':%s}]},open(a.result_file,'w'))\n" % ((2, 'True') if passing else (1, 'False')))
        rr = execute(f.root, 'GLOBAL', aid, 'GP1', [sys.executable, str(adapter)], str(f.target), f.base / ('exec-' + aid))
        receipt = json.loads(Path(rr['path']).read_text()); assertions = json.loads(Path(receipt['result_ref']['path']).read_text())['assertions']
        row = {'path_id': 'GP1', 'quality': 'green-passed' if passing else 'red-bug', 'executed': True, 'test_run_id': receipt['test_run_id'],
               'execution_receipt': rr, 'assertions': assertions}
        if not passing:
            row['root_cause'] = {'category': 'code', 'summary': 'integration result wrong', 'confidence': 'confirmed', 'owner': 'M001', 'next_action': 'fix'}
        return {'schema_version': 1, 'kind': 'tests', 'run_id': 'demo', 'module_id': 'GLOBAL', 'assignment_id': aid, 'actor_instance_id': 'wave-runner',
                'freeze_id': scope['freeze_id'], 'code_baseline': scope['code_baseline'], 'paths': [row]}

    def second_wave(self):
        f = self.f
        p = f.plan(); p['module_id'] = 'M002'; p['paths'][0].update(path_id='P2', case_id='C2'); p['tasks'][0]['path_ids'] = ['P2']
        f.call('plan', {'plan_ref': f.ref('p2.json', p)}, role='spec-designer', module='M002')
        f.call('decision', {'decision_id': 'D2', 'decision': 'approved', 'module_id': 'M002', 'subject_sha256': digest(p),
                            'human_source_ref': f.ref('d2.md', 'approved')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'D2'}, module='M002')
        f.implement('M002', 'I2'); f.verify_module('M002', 'T2'); f.complete('M002')

    def test_an_opaque_global_path_runs_early_and_retests_when_the_full_baseline_changes(self):
        f = self.f
        with self.assertRaisesRegex(Rejected, 'no global path is due'):
            f.call('integration-assign', {'assignment_id': 'INT0', 'instance_id': 'wave-runner', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        step = self.first_wave()
        self.assertEqual((step['operation'], step['reason'], step['path_ids']), ('integration-assign', 'wave-complete', ['GP1']))
        with self.assertRaisesRegex(Rejected, 'independent of code'):
            f.call('integration-assign', {'assignment_id': 'INT1', 'instance_id': 'implementer', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        f.call('integration-assign', {'assignment_id': 'INT1', 'instance_id': 'wave-runner', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        self.assertEqual(f.state()['global_next_step']['operation'], 'integration-submit')
        f.call('integration-submit', {'result_ref': f.ref('int1.json', self.run_gp1('INT1'))}, role='test-runner', instance='wave-runner', module=None)
        s = f.state()
        self.assertEqual((s['audit_results']['GP1']['quality'], s['audit_results']['GP1']['owner_baselines']),
                         ('green-passed', {'M001': s['modules']['M001']['code_baseline']}))
        self.assertTrue(s['integration_assignment']['closed']); self.assertNotEqual(s['global_next_step']['operation'], 'integration-assign')
        self.second_wave()
        s = f.state()
        self.assertNotEqual(ledger.global_baseline(s), s['audit_results']['GP1']['code_baseline'])  # the whole code moved, the owner's did not
        self.assertEqual([p['path_id'] for p in ledger.audit_scope(s)['plan']['paths']], ['GP1'])
        rows = {r['path_id']: r for r in __import__('migration_report').build(f.root, s, s['last_sequence'])['paths']}
        self.assertTrue(rows['GP1']['stale'])

    def test_stale_wave_requires_matching_host_stop_before_the_audit_can_take_over(self):
        f = self.f
        self.first_wave()
        f.call('integration-assign', {'assignment_id': 'INT1', 'instance_id': 'wave-runner', 'path_ids': ['GP1']},
               role='global-orchestrator', module=None)
        report = f.ref('int1.json', self.run_gp1('INT1'))
        self.second_wave()
        step = f.state()['global_next_step']
        self.assertEqual(step['operation'], 'integration-revoke')
        with self.assertRaisesRegex(Rejected, 'stop or isolate'):
            f.call('integration-submit', {'result_ref': report}, role='test-runner', instance='wave-runner', module=None)
        stopped = f.ref('wave-stop.md', 'Host verified the wave process exited.')
        with self.assertRaisesRegex(Rejected, 'fence mismatch'):
            f.call('integration-revoke', {**step['payload'], 'fencing_token': -1, 'stopped_worker_ref': stopped}, role='host', module=None)
        f.call('integration-revoke', {**step['payload'], 'stopped_worker_ref': stopped}, role='host', module=None)
        self.assertIsNone(integration.task(f.state()))
        self.assertEqual(f.state()['global_next_step']['operation'], 'audit-code-review')
        with self.assertRaisesRegex(Rejected, 'inactive'):
            f.call('integration-submit', {'result_ref': report}, role='test-runner', instance='wave-runner', module=None)

    def test_managed_visual_wave_binds_the_build_while_a_sibling_moves(self):
        f = self.f
        self.first_wave()
        self.second_wave()
        s = ledger.read_events(f.root)[0]
        owner, sibling = s['modules']['M001'], s['modules']['M002']
        env = f.root / 'runs/harmony/sandbox/environment/native.json'
        env.parent.mkdir(parents=True)
        env.write_text(json.dumps({'visual_capture': {'backend': 'adb', 'device_id': 'fixture'}}))
        artifact = f.root / 'runs/build/B1/app.apk'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b'accepted apk')
        build = {'path_id': 'B1', 'kind': 'build', 'command': {'selection_ref': f.ref('command.txt', 'assemble')}}
        owner['plan']['paths'].append(build)
        owner['build_artifacts'] = [file_ref(artifact)]
        owner['results']['B1'] = {'quality': 'green-passed', 'code_baseline': owner['code_baseline'],
                                  'build_artifacts': owner['build_artifacts']}
        path = s['global_paths'][0]
        path.update(kind='visual', platform='android', build_binding={'module_id': 'M001', 'path_id': 'B1'},
                    visual_execution={'environment_ref': file_ref(env)})
        sibling['phase'] = 'implementing'
        sibling_file = check_ref(sibling['code_files'][0])
        sibling_file.write_bytes(b'unrelated working copy changes')
        self.assertEqual(integration.due(s), [path])
        integration.handle(s, {'operation': 'integration-assign', 'payload': {
            'assignment_id': 'INT1', 'instance_id': 'wave-runner', 'path_ids': ['GP1']}},
            {'role': 'global-orchestrator', 'instance_id': 'go'}, 99)
        task = integration.task(s)
        self.assertEqual(set(task['snapshot']), {'M001'})
        self.assertTrue(task['artifact_only'])
        import context_readiness
        preflight = context_readiness.subject(s, None, 'audit-execution')
        sibling.update(code_files=[file_ref(sibling_file)], freeze_id='new sibling freeze')
        sibling['code_baseline'] = ledger.baseline(sibling['code_files'])
        self.assertFalse(integration.stale(s))
        self.assertEqual(context_readiness.subject(s, None, 'audit-execution'), preflight)
        self.assertEqual(integration.scope(s)['path_build_artifacts']['GP1'], [file_ref(artifact)])
        row = {'quality': 'green-passed', 'integration_inputs': task['inputs']['GP1'], 'code_baseline': task['code_baseline']}
        self.assertTrue(integration.current(s, path, row, ledger.global_baseline(s)))
        artifact.write_bytes(b'changed apk')
        self.assertTrue(integration.stale(s))
        self.assertFalse(integration.current(s, path, row, ledger.global_baseline(s)))

    def test_a_red_integration_result_is_routed_to_the_owning_leaf(self):
        f = self.f; self.first_wave()
        f.call('integration-assign', {'assignment_id': 'INT1', 'instance_id': 'wave-runner', 'path_ids': ['GP1']}, role='global-orchestrator', module=None)
        f.call('integration-submit', {'result_ref': f.ref('int1.json', self.run_gp1('INT1', passing=False))}, role='test-runner', instance='wave-runner', module=None)
        s = f.state()
        self.assertEqual((ledger.pending_repairs(s)['GP1']['module_ids'], s['audit_results']['GP1']['quality']), (['M001'], 'red-bug'))
        self.assertNotEqual(s['global_next_step']['operation'], 'integration-assign')  # red is routed, not re-run
        f.call('repair-accept', {'path_ids': ['GP1']}, module='M001')
        m = f.state()['modules']['M001']
        self.assertIn('GP1', m['repair_findings']); self.assertEqual(ledger.pending_repairs(f.state()), {})
        self.assertEqual([p['path_id'] for p in ledger.audit_scope(f.state())['plan']['paths']], ['GP1'])  # the audit still sees it until it is green again



class MechanicalWaveTests(unittest.TestCase):
    """A wave whose global path the run's stated adapter drives is dispatched and run by the Ledger."""
    first_wave = WaveIntegrationTests.first_wave

    def setUp(self):
        f = self.f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state(); f.root = f.base / 'wave'
        adapter = f.base / 'run-adapter.py'
        adapter.write_text("import argparse,json\np=argparse.ArgumentParser();p.add_argument('--query-file');p.add_argument('--result-file');a=p.parse_args()\n"
                           "json.dump({'assertions':[{'assertion_id':'A1','expected':2,'actual':2,'passed':True}]},open(a.result_file,'w'))\n")
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'global_spec', 'new_architecture')},
                        'dimension_slicing_required': False, 'split_testing_required': False, 'context_readiness_required': False,
                        'case_ids': ['C1', 'C2'], 'requirement_ids': ['R1'], 'max_fix_rounds': 1,
                        'test_adapter': {'executable': sys.executable, 'args': [str(adapter)]},
                        'global_paths': [{'path_id': 'GP1', 'case_id': 'C1', 'expected_assertions': [{'assertion_id': 'A1', 'expected': 2}]}]}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm1')]}, role='global-orchestrator', module=None)
        f.call('register', {'module_id': 'M002', 'case_ids': ['C2'], 'dependencies': ['M001'], 'write_paths': [str(f.target / 'm2')]}, role='global-orchestrator', module=None)
        f.global_plan(case_owners={'C1': ['M001', 'GLOBAL'], 'C2': ['M002']}, requirement_owners={'R1': ['M001', 'M002']})
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer'); f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})

    def test_the_wave_is_dispatched_and_run_by_the_ledger(self):
        f = self.f
        self.assertTrue(self.first_wave()['mechanical'])
        applied = ledger.advance_run(f.root, {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'})
        self.assertEqual([a['operation'] for a in applied], ['integration-assign', 'integration-submit'])
        s = f.state()
        self.assertEqual(s['audit_results']['GP1']['quality'], 'green-passed')
        self.assertTrue(s['integration_assignment']['closed'])


if __name__ == '__main__':
    unittest.main()
