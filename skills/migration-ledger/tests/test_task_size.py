"""A task that touched many files in one version is a signal, not a gate: a fact for the trace, a flag for the cursor and the audit."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import issues


class TaskSizeTests(unittest.TestCase):
    def test_a_large_task_is_a_fact_and_a_slicing_signal(self):
        s = {'modules': {'M001': {'module_id': 'M001', 'dependencies': [], 'task_files': {}}}}
        trace = [{'task_id': 'T1', 'files': ['/t/f%d.kt' % n for n in range(41)]}, {'task_id': 'T2', 'files': ['/t/one.kt']}]
        decomposition.task_size_facts(s, 'M001', trace, sequence=9)
        fact = s['issues']['SIZE-M001-T1']
        self.assertEqual((fact['kind'], fact['applies_to'], fact['sequence'], fact['raised_by']), ('fact', ['M001'], 9, issues.LEDGER))
        self.assertIn('41 files', fact['summary']); self.assertTrue(fact['resolved']['M001']['recorded'])
        self.assertNotIn('SIZE-M001-T2', s['issues'])
        self.assertEqual(issues.of_module(s, 'M001')[0], [])  # owed to nobody
        decomposition.task_size_facts(s, 'M001', trace, sequence=12)  # recorded once
        self.assertEqual(s['issues']['SIZE-M001-T1']['sequence'], 9)
        s['modules']['M001']['task_files'] = {row['task_id']: row['files'] for row in trace}
        signal = decomposition.slicing_signals(s)['M001']
        self.assertEqual((signal['large_tasks'], signal['flags']), (['T1'], ['large-tasks']))


if __name__ == '__main__':
    unittest.main()
