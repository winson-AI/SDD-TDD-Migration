import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from contracts import Rejected, file_ref, check_ref
import ledger
import project_context as pc


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / '.sdd-migration'; self.run = self.base / 'runs/r1'
        self.legacy = self.base / 'legacy'; self.legacy.mkdir()
        self.target = self.base / 'target'; self.target.mkdir()
        self.arch = self.base / 'architecture.md'; self.arch.write_text('architecture v1')
        self.source = self.base / 'user.txt'; self.source.write_text('User supplied these project settings.')
        self.actor = {'role': 'host', 'instance_id': 'test-host'}
        self.config = {'legacy_root': str(self.legacy), 'target_root': str(self.target),
                       'architecture_path': str(self.arch),
                       'defaults': {'entry_mode': 'project', 'budgets': {'max_parallel_modules': 2}},
                       'test_adapter': {'executable': sys.executable, 'args': ['test.py'], 'cwd': str(self.target)}}
        self.initial = self.request('init', 0, self.config)
        pc.update(self.root, self.initial, self.actor, initialize=True)

    def request(self, rid, revision, patch):
        return {'schema_version': 1, 'project_id': 'demo', 'request_id': rid,
                'expected_revision': revision, 'patch': patch, 'source_ref': file_ref(self.source)}

    def run_request(self, rid='r1', **kwargs):
        return {'schema_version': 1, 'project_id': 'demo', 'request_id': 'prepare-' + rid,
                'run_id': rid, 'source_ref': file_ref(self.source), **kwargs}

    def prepare(self, **kwargs):
        return pc.prepare(self.root, self.run, self.run_request(**kwargs), self.actor)

    def init_payload(self, result):
        source = self.base / 'generated-spec.md'; source.write_text('Global generated R1 and C1')
        data = result['input']
        return {**{k: data[k] for k in ('project_context_ref', 'legacy_root', 'target_root', 'entry_mode', 'module_name', 'new_architecture')},
                **{k: data['budgets'][k] for k in pc.BUDGETS},
                'single_module_id': 'M001' if data['entry_mode'] == 'single-module' else None,
                'global_spec': file_ref(source), 'case_ids': ['C1'], 'requirement_ids': ['R1'],
                'global_paths': [{'path_id': 'G1', 'case_id': 'C1', 'expected_assertions': [{'assertion_id': 'A1', 'expected': True}]}]}

    def start(self, payload, root=None):
        return ledger.apply(root or self.run, {'schema_version': 1, 'request_id': 'ledger-init', 'run_id': 'r1',
                        'operation': 'init', 'module_id': None, 'expected_revision': 0, 'payload': payload}, self.actor)

    def test_reuse_sources_are_saved_frozen_updated_and_visible(self):
        library = self.base / 'library'; library.mkdir()
        module = library / 'search'; module.mkdir()
        declared = [{'source_id': 'LIB', 'root': str(library), 'module_paths': [str(module)], 'description': 'Search capability'}]
        pc.update(self.root, self.request('reuse', 1, {'reuse_sources': declared}), self.actor)
        prepared = self.prepare()
        pc.update(self.root, self.request('remove-reuse', 2, {'reuse_sources': []}), self.actor)
        self.assertEqual(prepared['input']['reuse_sources'], declared)
        self.assertEqual(self.prepare()['input']['reuse_sources'], declared)
        self.start(self.init_payload(prepared))
        sources = ledger.status(self.run)['planning_context']['reuse_sources']
        self.assertEqual([s['source_id'] for s in sources], ['TARGET', 'LIB'])
        self.assertEqual(sources[1]['module_paths'], [str(module)])
        next_run = pc.prepare(self.root, self.base / 'runs/r2', self.run_request('r2'), self.actor)
        self.assertEqual(next_run['input']['reuse_sources'], [])

    def test_build_config_updates_and_environment_snapshot_is_frozen(self):
        env = self.base / 'build-env.md'; env.write_text('JDK and SDK v1')
        build = {'argv': [sys.executable, '-c', 'pass'], 'cwd': str(self.target),
                 'timeout_seconds': 90, 'environment_ref': str(env)}
        pc.update(self.root, self.request('build', 1, {'build': build}), self.actor)
        prepared = self.prepare()
        self.assertTrue(prepared['input']['split_testing_required'])
        frozen = prepared['input']['build']
        env.write_text('JDK and SDK v2')
        self.assertEqual(Path(frozen['environment_ref']).read_text(), 'JDK and SDK v1')
        pc.update(self.root, self.request('change-build', 2, {'build': {'argv': [sys.executable, '-V']}}), self.actor)
        self.start(self.init_payload(prepared))
        self.assertEqual(ledger.status(self.run)['planning_context']['build'], frozen)
        next_run = pc.prepare(self.root, self.base / 'runs/r2', self.run_request('r2'), self.actor)
        self.assertEqual(next_run['input']['build']['argv'], [sys.executable, '-V'])

    def test_prepared_run_requires_context_readiness(self):
        prepared = self.prepare()
        self.assertTrue(prepared['input']['context_readiness_required'])
        payload = self.init_payload(prepared)
        payload['context_readiness_required'] = False
        with self.assertRaisesRegex(Rejected, 'requires context readiness'):
            self.start(payload)
        payload.pop('context_readiness_required')
        self.start(payload)
        self.assertTrue(ledger.status(self.run)['context_readiness_required'])

    def test_reuse_sources_reject_escape_duplicates_and_input_override(self):
        library = self.base / 'library'; library.mkdir()
        source = {'source_id': 'LIB', 'root': str(library), 'module_paths': [str(library)]}
        for sources in ([source, source], [{**source, 'source_id': 'TARGET'}],
                        [{**source, 'module_paths': [str(self.target)]}], [{**source, 'root': 'relative'}]):
            with self.assertRaises(Rejected):
                pc.update(self.root, self.request('bad-reuse', 1, {'reuse_sources': sources}), self.actor)
        pc.update(self.root, self.request('reuse', 1, {'reuse_sources': [source]}), self.actor)
        prepared = self.prepare(); payload = self.init_payload(prepared); payload['reuse_sources'] = []
        with self.assertRaisesRegex(Rejected, 'reuse sources mismatch'):
            self.start(payload)

    def test_global_knowledge_is_frozen_and_visible_to_module_planning(self):
        knowledge = self.base / 'knowledge.md'
        knowledge.write_text('shared domain contracts v1')
        pc.update(self.root, self.request('knowledge', 1, {'knowledge_paths': [str(knowledge)]}), self.actor)
        result = self.prepare()
        ref = result['input']['project_sources']['knowledge_paths'][0]
        knowledge.write_text('shared domain contracts v2')
        self.assertEqual(check_ref(ref).read_text(), 'shared domain contracts v1')
        self.start(self.init_payload(result))
        context = ledger.status(self.run)['planning_context']
        self.assertEqual(context['project_sources']['knowledge_paths'], [ref])
        self.assertEqual(context['legacy_root'], str(self.legacy))
        self.assertEqual(context['target_root'], str(self.target))
        self.assertEqual(context['new_architecture'], result['input']['new_architecture'])
        check_ref(ref).write_text('tampered snapshot')
        with self.assertRaises(Rejected):
            ledger.status(self.run)

    def test_initialize_incremental_update_delete_and_history(self):
        pc.update(self.root, self.request('change', 1, {'test_adapter': {'args': ['other.py']},
                  'defaults': {'budgets': {'max_fix_rounds': 4}}, 'project_rules_path': str(self.arch)}), self.actor)
        config = pc.current(self.root)['config']
        self.assertEqual(config['test_adapter']['cwd'], str(self.target))
        self.assertEqual(config['test_adapter']['args'], ['other.py'])
        self.assertEqual(config['defaults']['budgets'], {'max_parallel_modules': 2, 'max_fix_rounds': 4})
        pc.update(self.root, self.request('delete', 2, {'project_rules_path': None}), self.actor)
        self.assertNotIn('project_rules_path', pc.current(self.root)['config'])
        self.assertEqual([r['revision'] for r in pc.history(self.root)], [3, 2, 1])
        self.source.write_text('Later user message')
        self.assertEqual(check_ref(pc.current(self.root)['source_ref']).read_text(), 'User supplied these project settings.')

    def test_idempotence_and_stale_updates(self):
        self.assertTrue(pc.update(self.root, self.initial, self.actor, initialize=True)['duplicate'])
        req = self.request('u1', 1, {'human_owner': 'owner'})
        pc.update(self.root, req, self.actor)
        self.assertTrue(pc.update(self.root, req, self.actor)['duplicate'])
        with self.assertRaisesRegex(Rejected, 'stale project revision'):
            pc.update(self.root, self.request('u2', 1, {}), self.actor)
        changed = copy.deepcopy(req); changed['patch']['human_owner'] = 'other'
        with self.assertRaisesRegex(Rejected, 'request id reused'):
            pc.update(self.root, changed, self.actor)

    def test_concurrent_updates_have_one_winner(self):
        def write(n):
            try:
                pc.update(self.root, self.request('u' + str(n), 1, {'human_owner': str(n)}), self.actor)
                return True
            except Rejected: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(write, [1, 2])), 1)
        self.assertEqual(pc.current(self.root)['revision'], 2)

    def test_partial_config_can_be_saved_but_not_prepared(self):
        root = self.base / 'partial'
        pc.update(root, self.request('partial', 0, {'legacy_root': str(self.legacy)}), self.actor, initialize=True)
        self.assertEqual(pc.current(root)['revision'], 1)
        with self.assertRaisesRegex(Rejected, 'missing directory'):
            pc.prepare(root, self.run, self.run_request(), self.actor)
        self.assertFalse((self.run / 'context/snapshot.json').exists())

    def test_configuration_rejects_worker_and_run_selection_fields(self):
        for patch in ({'module_name': 'login'}, {'run_id': 'x'}, {'defaults': {'entry_mode': 'single-module'}},
                      {'defaults': {'budgets': {'max_fix_rounds': 0}}}, {'target_root': str(self.legacy / 'child')}):
            with self.assertRaises(Rejected): pc.update(self.root, self.request('bad', 1, patch), self.actor)
        with self.assertRaisesRegex(Rejected, 'host principal'):
            pc.update(self.root, self.request('worker', 1, {}), {'role': 'implementer', 'instance_id': 'worker'})

    def test_prepare_freezes_docs_and_later_config_changes_do_not_change_old_run(self):
        result = self.prepare(entry_mode='single-module', module_name='Login')
        original_ref = copy.deepcopy(result['project_context_ref'])
        self.arch.write_text('architecture v2')
        new_target = self.base / 'target2'; new_target.mkdir()
        pc.update(self.root, self.request('target2', 1, {'target_root': str(new_target)}), self.actor)
        retry = self.prepare(entry_mode='single-module', module_name='Login')
        self.assertTrue(retry['duplicate']); self.assertEqual(retry['project_context_ref'], original_ref)
        self.assertEqual(retry['input']['target_root'], str(self.target))
        self.assertEqual(check_ref(retry['input']['new_architecture']).read_text(), 'architecture v1')
        result2 = pc.prepare(self.root, self.base / 'runs/r2', self.run_request('r2'), self.actor)
        self.assertEqual(result2['input']['target_root'], str(new_target))
        self.assertEqual(result2['input']['entry_mode'], 'project')
        self.assertIsNone(result2['input']['module_name'])
        self.assertEqual(check_ref(result2['input']['new_architecture']).read_text(), 'architecture v2')

    def test_temporary_overrides_do_not_persist_and_snapshot_cannot_be_replaced(self):
        result = self.prepare(overrides={'defaults': {'budgets': {'max_parallel_modules': 1}}})
        self.assertEqual(result['input']['budgets']['max_parallel_modules'], 1)
        self.assertEqual(pc.current(self.root)['config']['defaults']['budgets']['max_parallel_modules'], 2)
        with self.assertRaisesRegex(Rejected, 'already frozen'):
            self.prepare(entry_mode='single-module', module_name='Login')
        self.assertEqual(pc.current(self.root)['revision'], 1)

    def test_snapshot_is_independent_of_project_store(self):
        result = self.prepare()
        import shutil
        shutil.rmtree(self.root)
        self.arch.unlink(); self.source.unlink()
        self.assertEqual(pc.verify_snapshot(result['project_context_ref'])['project_revision'], 1)
        self.start(self.init_payload(result))
        self.assertEqual(ledger.status(self.run)['project_revision'], 1)

    def test_ledger_binds_scope_paths_budget_architecture_and_run(self):
        result = self.prepare(entry_mode='single-module', module_name='Login')
        payload = self.init_payload(result)
        for patch in ({'module_name': 'Other'}, {'entry_mode': 'project', 'single_module_id': None},
                      {'max_parallel_modules': 3}, {'new_architecture': file_ref(self.arch)},
                      {'target_root': str(self.base)}, {'project_context_ref': None}):
            with self.assertRaises(Rejected): self.start({**payload, **patch})
        with self.assertRaisesRegex(Rejected, 'different run'):
            self.start(payload, self.base / 'wrong-run')
        self.start(payload)
        state = ledger.status(self.run)
        self.assertEqual((state['project_id'], state['project_revision'], state['module_name']), ('demo', 1, 'Login'))
        pc.update(self.root, self.request('update', 1, {'human_owner': 'new owner'}), self.actor)
        self.assertEqual(ledger.status(self.run)['project_revision'], 1)

    def test_manual_edits_and_snapshot_corruption_are_rejected(self):
        path = self.root / 'project-context.json'
        original = path.read_bytes(); data = json.loads(original)
        data['config']['human_owner'] = 'unrecorded'; path.write_text(json.dumps(data))
        with self.assertRaisesRegex(Rejected, 'outside update protocol'): pc.current(self.root)
        path.write_bytes(original)
        result = self.prepare(); self.start(self.init_payload(result))
        check_ref(result['input']['new_architecture']).write_text('corrupt snapshot')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'): ledger.status(self.run)

    def test_cli_show_and_prepare(self):
        script = Path(pc.__file__)
        shown = subprocess.run([sys.executable, str(script), 'show', '--root', str(self.root)], capture_output=True, text=True)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)['revision'], 1)
        request_path = self.base / 'run-request.json'; request_path.write_text(json.dumps(self.run_request()))
        actor_path = self.base / 'host.json'; actor_path.write_text(json.dumps(self.actor))
        result = subprocess.run([sys.executable, str(script), 'prepare', '--root', str(self.root),
                '--run-root', str(self.run), '--request', str(request_path), '--host-context', str(actor_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['input']['entry_mode'], 'project')

    def test_source_json_is_frozen_without_following_its_old_paths(self):
        doc = self.base / 'input.json'
        doc.write_text(json.dumps({'architecture': file_ref(self.arch)}))
        request = self.run_request(); request['source_ref'] = file_ref(doc)
        result = pc.prepare(self.root, self.run, request, self.actor)
        self.arch.unlink(); doc.unlink()
        self.start(self.init_payload(result))
        self.assertEqual(ledger.status(self.run)['project_revision'], 1)

    def test_prepare_retry_rejects_manual_snapshot_edit_before_init(self):
        result = self.prepare()
        path = Path(result['project_context_ref']['path'])
        snapshot = json.loads(path.read_text()); snapshot['effective_config']['human_owner'] = 'other'
        path.write_text(json.dumps(snapshot))
        with self.assertRaisesRegex(Rejected, 'outside prepare protocol'):
            self.prepare()


if __name__ == '__main__': unittest.main()
