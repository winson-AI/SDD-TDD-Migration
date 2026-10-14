"""The Ledger writes a leaf's plan set as skeletons from its allocation; the author fills what only the author can write."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import contracts
import spec_skeleton
from contracts import Rejected, check_ref, file_ref
import test_control_policy
import test_source_changes


class DocumentCapTests(unittest.TestCase):
    def setUp(self):
        t = test_control_policy.ControlPolicyTests(); t.setUp(); self.addCleanup(t.doCleanups)
        self.f = t.f; self.f.global_plan()

    def test_the_skeleton_cites_the_allocation_and_has_no_decisions_section(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        result = spec_skeleton.write(t.f.root, 'M001', t.f.root / 'staging/spec-designer/skeleton')
        text = {name: check_ref(ref).read_text() for name, ref in result['files'].items()}
        self.assertNotIn('## Decisions', text['design.md'])
        self.assertIn('dimension_analysis_ref', text['design.md']); self.assertIn('M001-Logic', text['design.md'])
        out = t.f.state()['modules']['M001']['scope']['out']
        for name in ('proposal.md', 'design.md'):
            self.assertIn(f'scope.out（{len(out)} 条）', text[name])
            for line in out:
                self.assertNotIn(f'- {line}\n', text[name])


    def test_the_plan_set_is_written_from_the_allocation_and_filled_before_it_is_a_plan(self):
        t = test_source_changes.SourceChangeTests(); t.setUp(); self.addCleanup(t.doCleanups)
        out = t.f.root / 'staging/spec-designer/skeleton-set'
        result = spec_skeleton.write(t.f.root, 'M001', out)
        files = result['files']
        self.assertLessEqual({'proposal.md', 'spec.md', 'design.md', 'tasks.md', 'test-plan.md', 'upstream-test-plan.json', 'stage-plan.json', 'reuse-plan.json', 'reuse-fidelity.md'}, set(files))
        m = t.f.state()['modules']['M001']
        plan = json.loads(check_ref(files['stage-plan.json']).read_text()); upstream = json.loads(check_ref(files['upstream-test-plan.json']).read_text())
        paths = {p['path_id']: p for p in upstream['paths']}
        self.assertEqual({p['case_id'] for p in paths.values() if p['kind'] == 'automation'}, set(m['case_ids']))  # one behaviour path per case
        self.assertEqual({p['kind'] for p in paths.values()} - {'static'}, {'build', 'unit', 'automation'})
        self.assertEqual(plan['test_design_ref'], files['upstream-test-plan.json']); self.assertEqual(upstream['design_ref'], files['test-plan.md'])
        self.assertEqual([d['kind'] for d in plan['definitions']], ['proposal', 'spec', 'design', 'tasks'])
        for task in plan['tasks']:
            self.assertTrue(task['path_ids'] and set(task['path_ids']) <= set(paths)); self.assertEqual(task['scope']['write_paths'], m['write_paths'])
        self.assertEqual({row['item_id'] for row in plan['dimension_trace']}, {'M001-Logic'})
        self.assertTrue(all(row['task_ids'] and row['path_ids'] for row in plan['dimension_trace']))
        reuse = json.loads(check_ref(files['reuse-plan.json']).read_text())
        self.assertEqual([row['requirement_ids'] for row in reuse['mappings']], [[rid] for rid in m['scope']['requirement_ids']])
        self.assertEqual(reuse['mappings'][0]['fidelity']['alignment_ref'], files['reuse-fidelity.md'])
        self.assertGreater(result['unfilled'], 10); self.assertIn('contracts.py refs', result['next_action'])
        with self.assertRaisesRegex(Rejected, r'unfilled skeleton field left in (stage-plan|upstream-test-plan)\.json'):
            t.f.call('plan', {'plan_ref': files['stage-plan.json']}, role='spec-designer')
        with self.assertRaisesRegex(Rejected, 'refusing to overwrite'):
            spec_skeleton.write(t.f.root, 'M001', out)
        (out / 'scratch').mkdir(); (out / 'scratch/notes.txt').write_text('draft')
        refs = contracts.refs_in(out)
        self.assertEqual(set(refs), set(files)); self.assertEqual(refs['stage-plan.json'], files['stage-plan.json'])



if __name__ == '__main__':
    unittest.main()
