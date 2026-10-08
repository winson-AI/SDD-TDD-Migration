"""A finished run says what its retrospective has to turn into lessons, and a leaf's documents start from its analysis."""
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import behavior_contract
import experience
import spec_skeleton
from contracts import SKELETON_MARK, Rejected, check_ref, file_ref
import test_ledger
import test_source_changes

LAYERED = {'parent_module_id': 'M010', 'slices': 3, 'supporting': [], 'shared_cases': [], 'chain_depth': 3, 'waiting': 2,
           'layered_cases': ['C1'], 'single_layer': ['M001', 'M002']}


class RetrospectiveDueTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def test_a_clean_run_owes_no_retrospective(self):
        f = self.f; f.test_green_flow_and_independent_global_audit()
        step = f.state()['global_next_step']
        self.assertEqual(step['reason'], 'await-delivery-authorization')
        self.assertNotIn('retrospective_due', step)
        self.assertIsNone(experience.retrospective_due(f.state()))

    def test_what_stopped_the_run_is_due_at_its_end_until_a_retrospective_is_committed(self):
        f = self.f
        f.call('suspend', {'kind': 'human', 'reason': 'need decision', 'root_cause': 'ambiguous input', 'owner': 'human'})
        f.approve(f.state()['next_steps'][0]['approval_subject_sha256'], 'RESUME')
        f.call('resume', {'decision_id': 'RESUME'})
        self.assertNotIn('retrospective_due', f.state()['global_next_step'])  # asked when the run is finished, not while it works
        f.test_green_flow_and_independent_global_audit()
        self.assertEqual(f.state()['global_next_step']['retrospective_due'], {'observations': 1, 'signals': []})
        proof = f.ref('retrospective-proof.md', 'Committed review of the blocker')
        f.call('retrospect', {'lessons_ref': f.ref('retrospective.json', {'schema_version': 1, 'entries': [{
            'kind': 'planning-gap', 'summary': 'Ask for the missing input before planning', 'applicability': 'inputs a person owns',
            'root_cause': 'the input was assumed', 'strategy': 'list owned inputs at registration', 'result': 'one blocker fewer',
            'next_check': 'every owned input has a source', 'evidence_refs': [proof]}]})}, role='host', module=None)
        self.assertNotIn('retrospective_due', f.state()['global_next_step'])

    def test_what_the_slicing_itself_shows_is_a_signal(self):
        state = {'modules': {'M001': {'plan_rounds': [1, 4]}, 'M002': {}}, 'module_groups': {}}
        # the freeze that took four plans is both an observation to abstract and a signal about the slicing
        self.assertEqual(experience.retrospective_due(state), {'observations': 1, 'signals': ['plan-rounds']})
        import unittest.mock as mock
        with mock.patch.object(behavior_contract, 'slices', return_value=[LAYERED]):
            self.assertEqual(experience.retrospective_due({'modules': {}, 'module_groups': {}}),
                             {'observations': 0, 'signals': ['chain', 'waiting', 'layered']})
            facts = experience.slicing_facts({'modules': {'M001': {'plan_submissions': 2}}, 'module_groups': {}})
            body = experience.skill_body({'runs': {'first': {'entries': [], 'slicing': facts}}})
        self.assertIn('| 1 条（C1） | 2 | 2 |', body)  # cases cut by layer, single-layer slices, most plans for one freeze


class SkeletonTests(unittest.TestCase):
    def setUp(self):
        self.t = t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f
        self.out = self.f.root / 'staging/spec-designer/skeleton'

    def test_the_documents_start_from_what_the_ledger_accepted(self):
        f = self.f
        self.assertIn('spec_skeleton.py', next(step for step in f.state()['next_steps'] if step.get('module_id') == 'M001')['spec_skeleton'])
        result = spec_skeleton.write(f.root, 'M001', self.out)
        self.assertEqual(sorted(result['files']), ['design.md', 'proposal.md', 'spec.md', 'tasks.md'])
        self.assertGreater(result['unfilled'], 0)
        m = f.state()['modules']['M001']
        text = {name: check_ref(ref).read_text() for name, ref in result['files'].items()}
        for name in ('design.md', 'spec.md', 'tasks.md'):
            self.assertIn('M001-Logic', text[name], name)  # every allocated item is already named where the freeze looks for it
        self.assertIn('Requirement-ID: R1', text['spec.md'])
        self.assertIn('Scenario-ID: SCN-M001-001', text['spec.md'])
        self.assertIn(m['scope']['in'][0], text['proposal.md'])
        self.assertIn('- [ ] TASK-M001-001', text['tasks.md'])
        with self.assertRaisesRegex(Rejected, 'refusing to overwrite'):
            spec_skeleton.write(f.root, 'M001', self.out)
        with self.assertRaisesRegex(Rejected, 'a leaf that has its four-dimension analysis'):
            spec_skeleton.write(f.root, 'M010', self.out / 'parent')

    def test_a_filled_skeleton_is_a_specification_the_scenario_contract_reads(self):
        result = spec_skeleton.write(self.f.root, 'M001', self.out)
        path = check_ref(result['files']['spec.md'])
        path.write_text(re.sub(re.escape(SKELETON_MARK) + r'[^\]]*\]\]', 'written by its author', path.read_text()))
        index = behavior_contract.scenario_index({'module_id': 'M001', 'definitions': [{**file_ref(path), 'kind': 'spec'}]})
        self.assertEqual([(row['scenario_id'], row['requirement_id']) for row in index], [('SCN-M001-001', 'R1')])

    def test_a_plan_that_still_holds_a_mark_is_refused(self):
        f, t = self.f, self.t
        result = spec_skeleton.write(f.root, 'M001', self.out)
        plan = t.plan('M001')
        if f.state().get('test_design_required'):
            from test_design_stage import prepare_design
            prepare_design(f, plan, 'M001')
        plan['definitions'] = [{**result['files']['proposal.md'], 'kind': 'proposal'} if d['kind'] == 'proposal' else d for d in plan['definitions']]
        with self.assertRaisesRegex(Rejected, 'unfilled skeleton section left in proposal'):
            f.call('plan', {'plan_ref': f.ref('plan-with-skeleton.json', plan)}, role='spec-designer', module='M001')

    def test_the_command_prints_what_it_wrote(self):
        self.assertEqual(spec_skeleton.main(['--root', str(self.f.root), '--module', 'M001', '--out', str(self.out)]), 0)
        self.assertEqual(spec_skeleton.main(['--root', str(self.f.root), '--module', 'M001', '--out', str(self.out)]), 1)  # nothing is overwritten


if __name__ == '__main__':
    unittest.main()
