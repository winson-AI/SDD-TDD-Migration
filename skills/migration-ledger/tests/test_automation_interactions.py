"""A source-only UI can freeze and prove its declared behavior without invented pixels."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, baseline, check_ref, file_ref, read_json
import execute_test
import ledger
import test_completion
import test_validation
import ui_fidelity
import test_ui_frozen_contracts as frozen_fixtures


class AutomationInteractionTests(unittest.TestCase):
    def setUp(self):
        self.f = frozen_fixtures.FrozenUiContracts()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        tree = self.f.fixture['tree']
        for key in ('runtimeIndex', 'runtimeIndexSha256'):
            tree['generatedFrom'].pop(key)
        tree['screens'][0]['root'].pop('runtimeObservations')
        self.f.evidence.update(visual_mode='source-only', legacy_executable=False,
            ui_tree_ref=file_ref(self.f.n.write('evidence/source-only-tree.json', tree)))
        for key in ('runtime_index_ref', 'baseline_refs', 'capture_manifest_ref'):
            self.f.evidence.pop(key)
        self.gesture = {'id': 'settings-edge-back', 'action': 'edge_back_gesture',
                        'from': {'page_id': 'settings', 'state_id': 'base'},
                        'expected': {'app_foreground': False}}
        self.f.model['interactions'] = [self.gesture]
        self.module = self.f.module()
        self.path = {'path_id': 'P-BACK', 'kind': 'automation', 'interaction_id': self.gesture['id'],
                     'expected_assertions': [{'assertion_id': 'A-BACK', 'expected': True}]}
        self.module['plan']['paths'] = [self.path]
        self.code = file_ref(self.f.n.write('target/Main.kt', 'fun main() = Unit'))
        self.hap = file_ref(self.f.n.write('target/test.hap', b'unit-test-package'))
        self.module.update(code_files=[self.code], code_baseline=baseline([self.code]),
            build_artifacts=[self.hap], phase='testing', freeze_id='F1', results={})
        self.run = self.f.n.root / '.sdd-runs/gesture'
        self.run.mkdir(parents=True)

    def proof(self):
        evidence = file_ref(self.f.n.write('.sdd-runs/gesture/staging/device-observation.json',
            {'fixture': True, 'action': self.gesture['action'], 'from': self.gesture['from'],
             'observed': self.gesture['expected']}))
        return {'code_baseline': self.module['code_baseline'], 'hap_ref': self.hap,
                'required_interaction': copy.deepcopy(self.gesture), 'interaction_checks': [{
                    'id': self.gesture['id'], 'status': 'PASSED', 'action': self.gesture['action'],
                    'from': self.gesture['from'], 'observed': self.gesture['expected'],
                    'hap_sha256': self.hap['sha256'], 'code_baseline': self.module['code_baseline'],
                    'evidence_ref': evidence}]}

    def test_source_only_can_freeze_behavior_without_visual_path(self):
        ui_fidelity.freeze_gate(self.f.state, self.module)
        self.assertEqual(ui_fidelity.frozen_interaction(self.module, self.path), self.gesture)
        self.assertNotIn('baseline_ref', self.path)
        self.path['kind'] = 'visual'
        with self.assertRaisesRegex(Rejected, 'frozen runtime UI target'):
            ui_fidelity.freeze_gate(self.f.state, self.module)

    def test_behavior_obligation_cannot_be_omitted_or_replaced(self):
        for update, message in [({'interaction_id': None}, 'declared interactions'),
                                ({'interaction_id': 'another-id'}, 'declared interactions'),
                                ({'coverage': 'other:base:viewport'}, 'starting page/state')]:
            module = copy.deepcopy(self.module); module['plan']['paths'][0].update(update)
            with self.subTest(update=update), self.assertRaisesRegex(Rejected, message):
                ui_fidelity.freeze_gate(self.f.state, module)

    def test_green_requires_actual_frozen_gesture_current_build_and_observation(self):
        valid = {'quality': 'green-passed', 'interaction_evidence': self.proof()}
        test_validation.interaction_result(self.module, self.path, valid, valid)
        alterations = [lambda p: p.pop('required_interaction'),
            lambda p: p.update(code_baseline='old'),
            lambda p: p.update(hap_ref=file_ref(self.f.n.write('target/old.hap', b'old'))),
            lambda p: p['interaction_checks'][0].update(action='toolbar-back'),
            lambda p: p['interaction_checks'][0].update({'from': {'page_id': 'other'}}),
            lambda p: p['interaction_checks'][0].update(observed={'app_foreground': True}),
            lambda p: p['interaction_checks'][0].update(status='NOT_RUN'),
            lambda p: p['interaction_checks'][0].update(evidence_ref=None)]
        for index, alter in enumerate(alterations):
            record = copy.deepcopy(valid); alter(record['interaction_evidence'])
            with self.subTest(index=index), self.assertRaises(Rejected):
                test_validation.interaction_result(self.module, self.path, record, record)
        changed = copy.deepcopy(valid); changed['interaction_evidence']['code_baseline'] = 'old'
        with self.assertRaisesRegex(Rejected, 'captured report'):
            test_validation.interaction_result(self.module, self.path, changed, valid)

    def test_unavailable_results_do_not_invent_gesture_passes(self):
        for quality in ('red-bug', 'yellow-blocked'):
            row = {'quality': quality}
            test_validation.interaction_result(self.module, self.path, row, row)
            self.assertEqual(row, {'quality': quality})

    def test_audit_keeps_leaf_and_global_behavior_obligations(self):
        self.module['results'] = {self.path['path_id']: {'quality': 'yellow-blocked'}}
        global_path = {**self.path, 'path_id': 'GLOBAL-BACK', 'frozen_interaction': self.gesture}
        state = {'modules': {'M001': self.module}, 'global_paths': [global_path]}
        scope = ledger.audit_scope(state)
        self.assertEqual(ui_fidelity.frozen_interaction(scope, self.path), self.gesture)
        self.assertEqual(ui_fidelity.frozen_interaction(scope, global_path), self.gesture)
        self.module['results'][self.path['path_id']]['quality'] = 'green-passed'
        self.assertNotIn(self.path['path_id'], ledger.audit_scope(state)['frozen_interactions'])

    def test_real_executor_query_and_completion_preserve_behavior_proof(self):
        self.path['steps'] = ['Perform frozen back gesture']
        self.path['expected_assertions'][0]['after_step'] = 1
        proof = self.f.n.write('.sdd-runs/gesture/staging/proof.json', self.proof())
        scripts = str(Path(__file__).resolve().parents[1] / 'scripts')
        adapter = self.f.n.write('.sdd-runs/gesture/staging/adapter.py', f'''
import sys, json
from pathlib import Path
sys.path.insert(0, {scripts!r})
sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
from test_harmony_integration import step_evidence
from contracts import digest, file_ref
q = json.loads(Path(sys.argv[sys.argv.index('--query-file')+1]).read_text())
out = Path(sys.argv[sys.argv.index('--result-file')+1])
obs = out.parent/'observations.json'; obs.write_text('[]')
proof = json.loads(Path({str(proof)!r}).read_text())
assert q['frozen_interaction'] == proof['required_interaction']
out.write_text(json.dumps({{'producer':'harmony-adapter', 'query_sha256':digest(q),
    **{{k:q[k] for k in ('run_id','module_id','path_id','freeze_id','code_baseline')}},
    'quality':'green-passed', 'observations_ref':file_ref(obs), 'interaction_evidence':proof,
    'assertions':[{{'assertion_id':'A-BACK','expected':True,'actual':True,'passed':True}}],
    **step_evidence(q, out.parent)}}))
''')
        self.module['assignments'] = {'A1': {'assignment_id': 'A1', 'role': 'test-runner',
                                            'instance_id': 'runner', 'closed': False}}
        state = {'run_id': 'gesture', 'modules': {'M001': self.module}}
        with patch.object(execute_test, 'status', return_value=state):
            ref = execute_test.execute(self.run, 'M001', 'A1', 'P-BACK', [sys.executable, '-B', str(adapter)],
                self.f.n.target, self.run/'runs/harmony/automation/attempt', timeout=10)
        receipt = read_json(check_ref(ref))
        self.assertEqual(receipt['exit_code'], 0)
        query = read_json(check_ref(receipt['query_ref']))
        self.assertEqual(query['frozen_interaction'], self.gesture)
        self.assertNotIn('frozen_visual_evidence', query)
        row = test_completion.interpret(receipt, self.path)
        self.assertEqual(row['quality'], 'green-passed')
        test_validation.interaction_result(self.module, self.path, row, row)

    def init_request(self, path):
        spec = file_ref(self.f.n.write('input/spec.md', 'Frozen fixture requirement'))
        return {'schema_version': 1, 'request_id': 'init', 'run_id': 'gesture', 'module_id': None,
                'expected_revision': 0, 'operation': 'init', 'payload': {
                    'dimension_slicing_required': False, 'split_testing_required': False,
                    'context_readiness_required': False,
                    'target_root': str(self.f.n.target), 'legacy_root': str(self.f.n.android),
                    'case_ids': ['C1'], 'requirement_ids': ['R1'], 'global_spec': spec,
                    'new_architecture': spec, 'global_paths': [{**path, 'case_id': 'C1'}]}}

    def test_global_init_rejects_incomplete_contract_before_persisting(self):
        path = {**self.path, 'frozen_interaction': self.gesture,
                'build_binding': {'module_id': 'M001', 'path_id': 'BUILD1'}}
        for alteration in ({'frozen_interaction': None},
                           {'frozen_interaction': {**self.gesture, 'id': 'other'}},
                           {'build_binding': None}):
            for kind in ('automation', 'visual'):
                with self.subTest(kind=kind, alteration=alteration), self.assertRaises(Rejected):
                    ledger.apply(self.run, self.init_request({**path, 'kind': kind, **alteration}),
                                 {'role': 'host', 'instance_id': 'host'})
                self.assertEqual(ledger.read_events(self.run), (None, []))
        ledger.apply(self.run, self.init_request(path), {'role': 'host', 'instance_id': 'host'})
        state, _ = ledger.read_events(self.run)
        self.assertEqual(state['global_paths'][0]['frozen_interaction'], self.gesture)

if __name__ == '__main__':
    unittest.main()
