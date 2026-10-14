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


if __name__ == '__main__':
    unittest.main()
