"""A run runs to completion on the package it was prepared with; a rule written since binds the next run."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import package_version
import reading
from contracts import Rejected
import test_ledger


class PackagePinTests(unittest.TestCase):
    def test_the_package_commit_is_read_from_git_and_absent_elsewhere(self):
        self.assertRegex(package_version.sha(reading.PACKAGE), r'^[0-9a-f]{40}$')
        self.assertIsNone(package_version.sha(Path('/no-such-checkout-for-this-test')))
        self.assertIsNone(package_version.sha(None))

    def test_a_pinned_run_takes_requests_only_from_its_own_package_checkout(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        host = {'role': 'host', 'instance_id': 'host'}

        def start(name, pin, **extra):
            root = f.base / name
            payload = {'dimension_slicing_required': False, 'split_testing_required': False, 'context_readiness_required': False,
                       'target_root': str(f.target), 'legacy_root': str(f.legacy), 'case_ids': ['C1'], 'requirement_ids': ['R1'],
                       'global_spec': f.ref('global-spec.md', 'R1 spec'), 'new_architecture': f.ref('architecture.md', 'target architecture'),
                       'global_paths': [], 'package_sha': pin, **extra}
            ledger.apply(root, {'schema_version': 1, 'request_id': 'init-' + name, 'run_id': 'demo', 'module_id': None,
                                'expected_revision': 0, 'operation': 'init', 'payload': payload}, host)
            return lambda: ledger.apply(root, {'schema_version': 1, 'request_id': 'register-' + name, 'run_id': 'demo', 'module_id': None,
                                               'expected_revision': 1, 'operation': 'register',
                                               'payload': {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm1')]}},
                                        {'role': 'global-orchestrator', 'instance_id': 'go'})

        start('same-package', package_version.sha(reading.PACKAGE))()  # pinned to this checkout: every request goes through
        start('no-pin', None)()  # a run prepared before pins exist is not judged on its package
        with self.assertRaisesRegex(Rejected, 'pinned to package ffffffffffff'):
            start('other-package', 'f' * 40)()
        with self.assertRaisesRegex(Rejected, 'package_sha is a git commit'):
            start('bad-pin', 'nope')
        with self.assertRaisesRegex(Rejected, 'needs test_cases_path'):
            start('claimed-complete', None, module_slicing={'functional_use_cases_complete': True})

    def test_a_run_revision_with_a_decision_moves_the_run_to_this_package(self):
        f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        root, host, go = f.base / 'moved', {'role': 'host', 'instance_id': 'host'}, {'role': 'global-orchestrator', 'instance_id': 'go'}
        here = package_version.sha(reading.PACKAGE)
        n = iter(range(100))
        def call(op, payload, actor, scope=None):
            s = ledger.read_events(root)[0]
            return ledger.apply(root, {'schema_version': 1, 'request_id': f'{op}-{next(n)}', 'run_id': 'demo', 'module_id': None,
                                       'expected_revision': s['revision'] if s else 0, 'operation': op, 'payload': payload}, actor)
        call('init', {'dimension_slicing_required': False, 'split_testing_required': False, 'context_readiness_required': False,
                      'target_root': str(f.target), 'legacy_root': str(f.legacy), 'case_ids': ['C1'], 'requirement_ids': ['R1'],
                      'global_spec': f.ref('global-spec.md', 'R1 spec'), 'new_architecture': f.ref('architecture.md', 'target architecture'),
                      'global_paths': [], 'package_sha': 'f' * 40}, host)
        report = lambda sha: f.ref(f'move-{sha[:4]}.json', {'schema_version': 1, 'run_id': 'demo', 'reason': 'take the fixed rules in',
                                                             'context_patch': {}, 'root_updates': [], 'modules': [], 'package_sha': sha,
                                                             'boundary_review': {'semantic_change': False, 'authorization_change': False,
                                                                                 'unresolved_questions': [], 'reason': 'same task, newer rules',
                                                                                 'evidence_refs': [f.ref('move-why.md', 'fixed rules')]}})
        with self.assertRaisesRegex(Rejected, 'pinned to package'):
            call('run-review', {'report_ref': report('e' * 40)}, go)  # a revision to a package other than this checkout is judged from that one
        call('run-review', {'report_ref': report(here)}, go)
        subject = ledger.read_events(root)[0]['run_change_review']['subject_sha256']
        with self.assertRaisesRegex(Rejected, 'exact human decision'):
            call('revise-run', {'subject_sha256': subject}, host)  # the rules a run is held to change with a person's decision
        call('decision', {'decision_id': 'D-move', 'decision': 'approved', 'subject_sha256': subject,
                          'human_source_ref': f.ref('move-approval.md', 'approved: move the run to the fixed package')}, host)
        call('revise-run', {'subject_sha256': subject, 'decision_id': 'D-move'}, host)
        s = ledger.read_events(root)[0]
        self.assertEqual((s['package_sha'], s['run_change_history'][-1]['previous_package_sha']), (here, 'f' * 40))
        call('register', {'module_id': 'M001', 'case_ids': ['C1'], 'dependencies': [], 'write_paths': [str(f.target / 'm1')]}, go)


if __name__ == '__main__':
    unittest.main()
