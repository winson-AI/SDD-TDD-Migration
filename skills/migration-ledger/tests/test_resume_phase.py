"""A leaf whose every TASK is accepted keeps its code when its provider changes and, once the provider is back, goes on
at its tests: the step the Ledger offers it is a test run, not an implementer with nothing left to write."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import test_audit_closure
import test_decomposition
from contracts import digest


class ResumePhaseTests(unittest.TestCase):
    def test_a_fully_written_dependent_resumes_at_its_tests_after_its_provider_changed(self):
        f = test_decomposition.DecompositionTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.root_scope('project'); f.split(f.proposal(dependencies={'M002': ['M001']})); f.global_plan()
        f.prepare_leaf('M001'); f.complete_leaf('M001'); f.prepare_leaf('M002')
        before = f.state()['modules']['M002']
        self.assertEqual((before['phase'], before['accepted_task_ids']), ('testing', ['T1']))  # every TASK written and accepted
        f.call('change', {'request_ref': f.ref('cr.md', 'the contract gains a field'), 'impact_ref': f.ref('impact.md', 'no task moves')}, module='M001')
        waiting = f.state()['modules']['M002']
        self.assertEqual((waiting['phase'], waiting['blocked']['resume_phase']), ('waiting-dependency', 'testing'))  # not back to its freeze
        plan = copy.deepcopy(f.state()['modules']['M001']['plan']); plan['source_closure']['observable_result'] += ' (renewed)'
        f.call('plan', {'plan_ref': f.ref('plan-M001-2.json', plan)}, role='spec-designer', module='M001')
        f.call('decision', {'decision_id': 'M001-2', 'decision': 'approved', 'module_id': 'M001', 'subject_sha256': f.state()['modules']['M001']['plan_hash'],
                            'human_source_ref': f.ref('decision-M001-2.md', 'approved')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'M001-2'}, module='M001')
        test_audit_closure.ClosureTests.implement(f, 'M001', 'I2-M001')
        test_audit_closure.ClosureTests.verify_module(f, 'M001', 'T2-M001')
        f.call('complete', {'dod_ref': f.ref('dod-M001-2.md', 'reviewed')}, module='M001')
        # the provider's completion is a fact the Ledger holds: release, resume and the test dispatch take no model turn
        applied = ledger.advance(f.root, {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}, 'M002')['applied']
        self.assertEqual([(a['operation'], a.get('role')) for a in applied][:3], [('dependency-ready', None), ('resume', None), ('assign', 'test-runner')])
        after = f.state()['modules']['M002']
        self.assertEqual((after['phase'], after['code_baseline'], after['accepted_task_ids']), ('testing', before['code_baseline'], ['T1']))  # its code stands; it tests again


if __name__ == '__main__':
    unittest.main()
