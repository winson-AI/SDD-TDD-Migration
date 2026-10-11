"""The implementer declares, per task, whether its unit tests came before the code. The declaration is one of two words
the Ledger knows and the audit can count; nothing is enforced on it."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_audit_closure
from contracts import Rejected, baseline, file_ref


class DeclaredOrderTests(unittest.TestCase):
    def test_the_order_of_tests_and_code_is_declared_per_task_in_a_known_word(self):
        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare()
        f.call('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer'}, module='M001')
        a = f.state()['modules']['M001']['assignments']['I1']
        path = f.target / 'm1' / 'code.py'; path.parent.mkdir(exist_ok=True); path.write_text('value = 2\nshared = 1\n')
        refs = [file_ref(path)]

        def result(order, n):
            return f.ref(f'impl-{n}.json', {'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
                                             'assignment_id': 'I1', 'actor_instance_id': 'implementer', 'freeze_id': a['freeze_id'],
                                             'code_files': refs, 'code_baseline': baseline(refs),
                                             'task_trace': [{'task_id': 'T1', 'files': [str(path)], 'test_order': order}],
                                             'production_binding_evidence': f.ref('binding.md', 'reviewed production binding'),
                                             'authoring_diagnostics': {'status': 'passed', 'tool': 'fixture-lint',
                                                                       'log_ref': f.ref('authoring.log', 'changed files: 0 errors')}})

        with self.assertRaises(Rejected) as caught:
            f.call('submit', {'assignment_id': 'I1', 'fencing_token': a['fencing_token'], 'result_ref': result('later', 1)}, role='implementer', module='M001')
        self.assertIn('task test_order is tests-first or code-first', str(caught.exception))
        f.call('submit', {'assignment_id': 'I1', 'fencing_token': a['fencing_token'], 'result_ref': result('code-first', 2)}, role='implementer', module='M001')
        f.call('accept', {'assignment_id': 'I1'}, module='M001')  # declared, and nothing hangs on the word


if __name__ == '__main__':
    unittest.main()
