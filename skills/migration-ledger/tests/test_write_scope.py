"""Optional write-scope check: what a code worker changed must be declared and inside its scope."""
from pathlib import Path
import subprocess
import unittest

import test_ledger
import write_scope
from contracts import Rejected, baseline, file_ref


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class WriteScopeTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state()
        f.root = f.base / 'scope-run'
        f.call('init', {**{k: original[k] for k in ('target_root', 'legacy_root', 'case_ids', 'requirement_ids', 'global_spec',
                 'new_architecture', 'global_paths')}, 'dimension_slicing_required': False, 'split_testing_required': False,
                 'context_readiness_required': False, 'write_scope_check': True}, role='host')
        for mid, sub in (('M001', 'm1'), ('M002', 'm2')):
            f.call('register', {'module_id': mid, 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / sub)]},
                   role='global-orchestrator', module=None)
        git(f.target, 'init', '-q', '-b', 'main')
        git(f.target, 'config', 'user.email', 'fixture@example.invalid'); git(f.target, 'config', 'user.name', 'fixture')
        (f.target / 'README.md').write_text('baseline\n')
        git(f.target, 'add', 'README.md'); git(f.target, 'commit', '-q', '-m', 'baseline')
        (f.target / 'README.md').write_text('dirty before the worker started\n')  # pre-existing dirt is not the worker's
        f.prepare()

    def dispatch(self, aid='I1'):
        f = self.f
        assignment = f.assign('implementer', aid)
        self.base_receipt = f.base / (aid + '-baseline.json')
        write_scope.baseline(f.root, 'M001', aid, self.base_receipt)
        return assignment

    def submit(self, assignment, files, receipt=True):
        f = self.f; aid = assignment['assignment_id']
        refs = [file_ref(p) for p in files]
        result = {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
                  'assignment_id': aid, 'actor_instance_id': 'implementer', 'freeze_id': assignment['freeze_id'],
                  'code_files': refs, 'code_baseline': baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [str(p) for p in files]}],
                  'production_binding_evidence': f.ref('binding.txt', 'real binding reviewed'),
                  'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint', 'log_ref': f.ref('diag.log', '0 errors')}}
        payload = {'assignment_id': aid, 'fencing_token': assignment['fencing_token'],
                   'result_ref': f.ref(f'result-{f.n}.json', result)}
        if receipt:
            out = f.base / f'{aid}-delta-{f.n}.json'
            write_scope.delta(f.root, 'M001', aid, self.base_receipt, out)
            payload['write_scope_ref'] = file_ref(out)
        f.call('submit', payload, role='implementer')

    def code(self, name='m1/code.py', text='value = 2\n'):
        path = self.f.target / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        return path

    def test_declared_changes_inside_scope_are_accepted_despite_older_dirt(self):
        a = self.dispatch()
        self.submit(a, [self.code()])
        self.f.call('accept', {'assignment_id': 'I1'})
        self.assertEqual(self.f.state()['modules']['M001']['phase'], 'testing')

    def test_undeclared_file_inside_scope_is_rejected(self):
        a = self.dispatch()
        code = self.code(); self.code('m1/extra.py', 'helper = 1\n')
        with self.assertRaisesRegex(Rejected, 'undeclared change inside module scope'):
            self.submit(a, [code])

    def test_change_outside_every_authorised_scope_is_rejected(self):
        a = self.dispatch()
        code = self.code(); self.code('shared/config.py', 'flag = True\n')
        with self.assertRaisesRegex(Rejected, 'write outside module scope'):
            self.submit(a, [code])
        self.code('m2/other.py', 'x = 1\n')  # M002 has no open code assignment: also not authorised
        (self.f.target / 'shared/config.py').unlink()
        with self.assertRaisesRegex(Rejected, 'write outside module scope'):
            self.submit(a, [code])

    def test_receipt_is_required_and_must_match_current_files(self):
        a = self.dispatch()
        code = self.code()
        with self.assertRaisesRegex(Rejected, 'write_scope_ref'):
            self.submit(a, [code], receipt=False)
        out = self.f.base / 'stale-delta.json'
        write_scope.delta(self.f.root, 'M001', 'I1', self.base_receipt, out)
        code.write_text('value = 3\n')  # changed after the delta was taken
        with self.assertRaises(Rejected):
            refs = [file_ref(code)]
            self.f.call('submit', {'assignment_id': 'I1', 'fencing_token': a['fencing_token'],
                                   'write_scope_ref': file_ref(out),
                                   'result_ref': self.f.ref('stale-result.json', {
                                       'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
                                       'assignment_id': 'I1', 'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'],
                                       'code_files': refs, 'code_baseline': baseline(refs),
                                       'task_trace': [{'task_id': 'T1', 'files': [str(code)]}],
                                       'production_binding_evidence': self.f.ref('binding.txt', 'real binding reviewed'),
                                       'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint',
                                                                 'log_ref': self.f.ref('diag.log', '0 errors')}})},
                        role='implementer')

    def test_workflow_assets_inside_the_target_repo_are_not_target_changes(self):
        f = self.f
        assets = f.target / '.sdd-runs/demo'
        (assets / 'staging').mkdir(parents=True); (assets / 'staging/report.json').write_text('{}')
        (f.target / 'openspec').mkdir(); (f.target / 'openspec/spec.md').write_text('spec')
        dirty = write_scope._dirty(f.target, write_scope.managed_roots(assets))
        self.assertEqual([Path(p).name for p in dirty], ['README.md'])

    def test_disabled_by_default(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implementation()
        self.assertEqual(f.state()['modules']['M001']['phase'], 'testing')


if __name__ == '__main__':
    unittest.main()
