"""Optional per-module Git checkpoint: explicit module paths on the run branch, verified by the Ledger."""
import json
from pathlib import Path
import subprocess
import unittest

import test_ledger
import git_checkpoint
from contracts import Rejected, file_ref


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class GitCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state()
        f.root = f.base / 'checkpoint-run'
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec',
                 'new_architecture', 'global_paths')}, 'dimension_slicing_required': False, 'split_testing_required': False,
                 'context_readiness_required': False, 'git_checkpoint': True}, role='host')
        f.call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm1')]},
               role='global-orchestrator', module=None)
        git(f.target, 'init', '-q', '-b', 'main')
        git(f.target, 'config', 'user.email', 'fixture@example.invalid'); git(f.target, 'config', 'user.name', 'fixture')
        (f.target / 'README.md').write_text('baseline\n')
        git(f.target, 'add', 'README.md'); git(f.target, 'commit', '-q', '-m', 'pre-migration baseline')
        git(f.target, 'checkout', '-q', '-b', 'sdd/demo')  # host-authorised run branch

    def at_dod(self):
        f = self.f
        f.prepare(); f.implementation()
        a, result = f.make_test_result()
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['modules']['M001']['phase'], 'dod')

    def checkpoint(self, name='checkpoint.json'):
        out = self.f.base / name
        git_checkpoint.commit(self.f.root, 'M001', out)
        return file_ref(out)

    def test_completion_waits_for_a_checkpoint_of_exactly_the_module_paths(self):
        f = self.f; self.at_dod()
        (f.target / 'README.md').write_text('unrelated dirty edit\n')
        step = f.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['role']), ('checkpoint', 'host'))
        with self.assertRaisesRegex(Rejected, 'git checkpoint'):
            f.call('complete', {'dod_ref': f.ref('dod.md', 'reviewed')})
        receipt = self.checkpoint()
        f.call('checkpoint', {'receipt_ref': receipt}, role='host')
        committed = git(f.target, 'show', '--name-only', '--format=', 'HEAD').split()
        self.assertEqual(committed, ['m1/code.py'])
        self.assertIn('README.md', git(f.target, 'status', '--porcelain'))  # pre-existing dirt untouched
        f.call('complete', {'dod_ref': f.ref('dod.md', 'reviewed')})
        self.assertEqual(f.state()['modules']['M001']['git_checkpoint']['commit'], git(f.target, 'rev-parse', 'HEAD'))

    def test_wrong_branch_is_refused(self):
        f = self.f; self.at_dod()
        git(f.target, 'checkout', '-q', 'main')
        with self.assertRaisesRegex(Rejected, 'sdd/demo'):
            self.checkpoint()

    def test_ledger_rejects_a_receipt_that_does_not_match_current_files(self):
        f = self.f; self.at_dod()
        receipt = self.checkpoint()
        data = json.loads(Path(receipt['path']).read_text())
        data['files'][0]['blob'] = '0' * 40
        with self.assertRaisesRegex(Rejected, 'blob'):
            f.call('checkpoint', {'receipt_ref': f.ref('forged.json', data)}, role='host')

    def test_rerun_on_already_committed_paths_reuses_head(self):
        f = self.f; self.at_dod()
        first = json.loads(Path(self.checkpoint()['path']).read_text())
        second = json.loads(Path(self.checkpoint('again.json')['path']).read_text())
        self.assertEqual(first['commit'], second['commit'])

    def test_disabled_by_default(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        a, result = f.make_test_result()
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        self.assertEqual(f.state()['next_steps'][0]['operation'], 'complete')
        with self.assertRaisesRegex(Rejected, 'not enabled'):
            f.call('checkpoint', {'receipt_ref': f.ref('x.json', {})}, role='host')


if __name__ == '__main__':
    unittest.main()
