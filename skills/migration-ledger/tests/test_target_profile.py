"""The target's state per feature is recorded once and read by the split, the freeze and the report."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import migration_report
import target_profile
import test_context_readiness
import test_decomposition
import test_ledger
from contracts import Rejected, digest
import ledger


def profile(f, rows, target=None):
    return f.ref(f'target-profile-{f.n}.json', {'schema_version': 1, 'target_root': target or str(f.target), 'features': [
        {'feature_id': key, 'state': state, 'entry_points': [], 'symbols': [] if state == 'absent' else [str(f.target / 'm1/code.py') + '#value'],
         'build_unit': 'm1', 'tests': False, 'evidence_refs': [f.ref('target-review.md', 'read the target tree')]} for key, state in rows]})


class TargetProfileTests(unittest.TestCase):
    def test_the_global_plan_binds_a_profile_that_covers_the_inventory(self):
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        with self.assertRaisesRegex(Rejected, 'omits features'):
            f.global_plan(target_profile_ref=profile(f, [('F-other', 'absent')]))
        with self.assertRaisesRegex(Rejected, 'target state is one of'):
            f.global_plan(target_profile_ref=profile(f, [('F1', 'unknown')]))
        f.global_plan(target_profile_ref=profile(f, [('F1', 'partial')]))
        s = f.state()
        self.assertEqual(target_profile.rows(s)['F1']['state'], 'partial')
        self.assertEqual(decomposition.assigned_module(s, s['modules']['M001'])['target_profile'][0]['state'], 'partial')
        self.assertEqual(target_profile.report(s), [{'key': 'F1', 'state': 'partial', 'modules': ['M001'], 'entry_points': [], 'tests': False, 'symbols': 1}])

    def test_a_leaf_whose_target_holds_code_owes_its_reuse_at_freeze(self):
        f = test_context_readiness.ContextReadinessTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan(target_profile_ref=profile(f, [('F1', 'existing')]))
        plan = f.plan()
        f.call('plan', {'plan_ref': f.ref('plan.json', plan)}, role='spec-designer')
        self.assertTrue(any('already holds existing code' in gap['reason'] for gap in ledger.preview(f.root, 'M001')['owed']))  # the author sees it
        f.approve(digest(plan), 'D1'); f.call('freeze', {'decision_id': 'D1'})
        owed = [i for k, i in f.state().get('issues', {}).items() if k.startswith('OWED-M001-') and 'already holds existing code' in i['summary']]
        self.assertEqual(len(owed), 1); self.assertFalse(owed[0]['resolved'])  # recorded at freeze, the first version goes on

    def test_a_scaffold_needs_a_target_without_a_shell(self):
        d = test_decomposition.DecompositionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        d.root_scope()
        s = d.state(); root = s['modules']['M010']
        self.assertTrue(root.get('decomposition_required'))
        ref = profile(d, [('F-ROOT', 'existing')])
        # the root records its profile at registration: a fresh run registers it with the profile bound
        original = s; d.root = d.base / 'profiled-run'
        d.call('init', {**{k: original[k] for k in ('dimension_slicing_required', 'split_testing_required', 'context_readiness_required', 'target_root', 'legacy_root', 'case_ids',
                   'requirement_ids', 'global_spec', 'new_architecture', 'global_paths')}, 'entry_mode': 'single-module', 'single_module_id': 'M010'}, role='host')
        inventory = {'test_summary_ref': None, 'source_units': [], 'features': [{'feature_id': 'F-ROOT', 'name': 'Search', 'functional_path': 'Search/Root',
                     'trigger': 'invoke', 'observable_result': 'result', 'requirement_ids': ['R1'], 'case_ids': ['C1'], 'evidence_refs': []}]}
        d.call('register', {'module_id': 'M010', 'name': 'Search', 'case_ids': ['C1'], 'write_paths': [str(d.target)], 'dependencies': [], 'decomposition_required': True,
                            **({'feature_inventory_ref': d.ref('root-inventory.json', inventory)} if original.get('context_readiness_required') else {}),
                            'target_profile_ref': ref, 'scope': {'in': ['Search'], 'out': ['Orders'], 'requirement_ids': ['R1']},
                            'context_refs': [d.ref('search-context.md', 'Search entry, reuse contracts, architecture and testing list')]},
               role='global-orchestrator', module=None)
        self.assertEqual(target_profile.rows(d.state())['F-ROOT']['state'], 'existing')
        plan = d.proposal()  # the fixture's second child is a scaffold
        self.assertTrue(any(c.get('kind') == 'scaffold' for c in plan['children']))
        with self.assertRaisesRegex(Rejected, 'target profile says the shell is missing'):
            d.call('decompose', {'plan_ref': d.ref('split-M010.json', plan)}, module='M010')


if __name__ == '__main__':
    unittest.main()
