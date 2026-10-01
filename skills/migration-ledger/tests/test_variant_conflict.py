"""A runtime page variant that contradicts the frozen SPEC is a user scope decision, not a code fix."""
import unittest

import test_workflow
import lean_adapter
from contracts import Rejected

VARIANT = 'runtime-spec-variant-conflict'


class VariantConflictTests(unittest.TestCase):
    def test_lean_validation_issue_becomes_a_human_yellow(self):
        result = lean_adapter.validation_summary({
            'verdict': 'NEEDS_IMPLEMENTATION_FIX', 'checks': [{'kind': 'compile', 'status': 'passed'}],
            'issues': [{'category': VARIANT, 'message': 'capture shows live tab; SPEC freezes trending', 'owner': 'lean'}]})
        self.assertEqual(result['quality'], 'yellow-blocked')
        self.assertEqual((result['root_cause']['category'], result['root_cause']['reason_code'],
                          result['root_cause']['confidence']), ('human', VARIANT, 'confirmed'))

    def test_cursor_suspends_for_the_user_instead_of_a_fixer_round(self):
        w = test_workflow.WorkflowTests(); w.setUp(); self.addCleanup(w.doCleanups)
        w.prepare(); w.implementation()
        a, r = w.make_test_result(quality='red-bug')
        r['paths'][0]['quality'] = 'yellow-blocked'
        r['paths'][0]['root_cause'] = {'category': 'human', 'reason_code': VARIANT, 'confidence': 'confirmed',
                                       'summary': 'runtime shows a different variant than the frozen SPEC',
                                       'owner': 'human', 'next_action': 'ask the user which variant to keep'}
        w.submit(r, a); w.call('accept', {'assignment_id': 'TEST1'})
        step = w.state()['next_steps'][0]
        self.assertEqual((step['operation'], step['payload']['kind'], step['payload']['reason_code']), ('suspend', 'human', VARIANT))
        with self.assertRaises(Rejected):
            w.call('assign', {'assignment_id': 'F1', 'role': 'fixer', 'instance_id': 'fixer'})
        w.call('suspend', step['payload'])
        self.assertEqual(w.state()['modules']['M001']['phase'], 'waiting-human')


if __name__ == '__main__':
    unittest.main()
