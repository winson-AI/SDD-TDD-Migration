"""Small fixes a hosted run asked for: a plan under review still shows what a resubmission binds; a plan submitted
again says what it changes; a provider that reopened its contract is not there for a dependent, in the gate and in
the cursor alike; files submitted under a plan that is given up are carried like accepted ones."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import design_stage
import ledger
import test_ledger
import test_upstream_revision
from contracts import Rejected, file_ref


class ReviewStepTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()

    def test_a_plan_under_review_still_shows_what_a_resubmission_binds(self):
        f = self.f
        f.call('plan', {'plan_ref': f.ref('plan.json', f.plan())}, role='spec-designer')
        view = ledger.status(f.root, 'step', 'M001')
        s = ledger.read_events(f.root)[0]
        self.assertEqual(view['step']['operation'], 'plan-review')
        self.assertEqual(view['step']['resubmit'], {'input_subject_sha256': design_stage.subject(s, s['modules']['M001']),
                                                    'upstream_case_refs': design_stage.upstream_refs(s), 'upstream_case_ids': ['C1']})

    def test_a_plan_submitted_again_says_what_it_changes_until_it_is_frozen(self):
        f = self.f
        first = f.plan()
        f.call('plan', {'plan_ref': f.ref('plan-1.json', first)}, role='spec-designer')
        self.assertNotIn('plan_changes', f.state()['modules']['M001'])  # nothing to compare the first one with
        second = copy.deepcopy(first)
        second['paths'].append({'path_id': 'P2', 'name': 'again', 'case_id': 'C1', 'requirement_id': 'R1',
                                'expected_assertions': [{'assertion_id': 'A2', 'expected': 3}]})
        second['tasks'][0]['path_ids'] = ['P1', 'P2']
        f.call('plan', {'plan_ref': f.ref('plan-2.json', second)}, role='spec-designer')
        module = f.state()['modules']['M001']
        self.assertEqual(module['plan_changes'], {'paths': {'added': ['P2'], 'removed': [], 'changed': []},
                                                  'tasks': {'added': [], 'removed': [], 'changed': ['T1']}})
        self.assertEqual(ledger.status(f.root, 'module', 'M001')['module']['plan_changes'], module['plan_changes'])  # the reviewer reads it
        f.call('plan', {'plan_ref': f.ref('plan-2.json', second)}, role='spec-designer')  # the same plan again: nothing changed
        self.assertNotIn('plan_changes', f.state()['modules']['M001'])
        third = copy.deepcopy(second); third['decision_envelope']['allowed_alternatives'] = ['shape']
        f.call('plan', {'plan_ref': f.ref('plan-3.json', third)}, role='spec-designer')
        self.assertEqual(f.state()['modules']['M001']['plan_changes'], {'fields': ['decision_envelope']})
        f.approve(f.state()['modules']['M001']['plan_hash'], 'D1'); f.call('freeze', {'decision_id': 'D1'})
        self.assertNotIn('plan_changes', f.state()['modules']['M001'])


class ProviderInChangeTests(unittest.TestCase):
    def test_a_provider_that_reopened_its_contract_is_still_there_for_a_dependent_that_needs_its_code(self):
        d = test_upstream_revision.DependentTests('test_a_leaf_without_code_keeps_its_plan_and_is_left_to_move'); self.addCleanup(d.doCleanups)
        f, before, consumer = d.revised_provider(coded=False)
        state = f.state()
        self.assertEqual(state['modules']['M001']['phase'], 'change-review')
        self.assertTrue(state['modules']['M001']['code_baseline'])  # the code is still accepted, the contract is open
        row, = ledger.providers(state, consumer)
        self.assertEqual((row['module_id'], row['ready'], row['revising']), ('M001', True, True))
        f.call('assign', {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'implementer'}, module='M002')  # the code it needs is accepted
        self.assertIn('I1', f.state()['modules']['M002']['assignments'])


class CarriedFilesTests(unittest.TestCase):
    def test_files_submitted_under_the_plan_given_up_are_carried_whether_or_not_they_were_accepted(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        accepted = base / 'a.kt'; accepted.write_text('a')
        submitted = base / 'b.kt'; submitted.write_text('b')
        gone = {'path': str(base / 'gone.kt'), 'sha256': '0' * 64}
        result = base / 'result.json'
        result.write_text(json.dumps({'kind': 'implementation', 'code_files': [file_ref(accepted), file_ref(submitted), gone]}))
        m = {'module_id': 'M001', 'revision': 3, 'phase': 'frozen', 'plan': {'tasks': []}, 'code_files': [file_ref(accepted)],
             'submissions': {'I2': {'kind': 'implementation', 'ref': file_ref(result)}, 'T1': {'kind': 'tests', 'ref': file_ref(result)}}}
        ledger.reset_plan(m)
        self.assertEqual(sorted(ref['path'] for ref in m['carried_files']), [str(accepted), str(submitted)])  # once each, and only what exists
        self.assertEqual(m['phase'], 'specifying')
        bare = {'module_id': 'M002', 'revision': 1, 'phase': 'frozen', 'plan': {'tasks': []}, 'code_files': []}
        ledger.reset_plan(bare)
        self.assertNotIn('carried_files', bare)


if __name__ == '__main__':
    unittest.main()
