"""A split the Ledger drafted is accepted when the orchestrator submits it, and the GO's coverage is carried to the
children: from register to the first leaf plan the GO judges twice, not four times."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ledger
import split_draft
import test_ledger
import workflow
from contracts import read_json

CASES = ['C%d' % n for n in range(1, 7)]


class SplitAcceptTests(unittest.TestCase):
    def setUp(self, covered=True):
        self.f = f = test_ledger.FlowTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        original = f.state(); f.root = f.base / ('six-case-run' if covered else 'uncovered-run')
        f.call('init', {**{k: original[k] for k in ('dimension_slicing_required', 'split_testing_required', 'context_readiness_required',
                                                     'target_root', 'legacy_root', 'requirement_ids', 'global_spec', 'new_architecture')},
                        'case_ids': CASES, 'global_paths': []}, role='host')
        feature = lambda fid, path, cases: {'feature_id': fid, 'name': fid, 'functional_path': path, 'trigger': 'tap', 'observable_result': 'shown',
                                             'requirement_ids': ['R1'], 'case_ids': cases, 'evidence_refs': []}
        f.call('register', {'module_id': 'M010', 'name': 'Login', 'case_ids': CASES, 'write_paths': [str(f.target)], 'dependencies': [],
                            'decomposition_required': True, 'scope': {'in': ['Login'], 'out': [], 'requirement_ids': ['R1']},
                            'context_refs': [f.ref('login-context.md', 'login entry and architecture')],
                            'feature_inventory_ref': f.ref('login-inventory.json', {'features': [
                                feature('F-PHONE', 'Login/Phone', CASES[:3]), feature('F-CODE', 'Login/Code', CASES[3:])]})},
               role='global-orchestrator', module=None)
        if covered:
            f.call('global-plan', {'plan_ref': f.ref('coverage.json', {'boundary_review': {'issues': []}, 'requirement_owners': {'R1': ['M010']},
                                                                   'case_owners': {cid: ['M010'] for cid in CASES}}),
                                   'review_ref': f.ref('coverage.md', 'all covered')}, role='global-orchestrator', module=None)

    def test_coverage_the_registrations_state_is_written_by_the_ledger(self):
        self.doCleanups(); self.setUp(covered=False); f = self.f
        step = f.state()['global_next_step']
        self.assertEqual((step['operation'], step['mechanical'], step['reason']), ('global-plan', True, 'coverage-from-registrations'))
        applied = ledger.advance_run(f.root, {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'})
        self.assertEqual([a['operation'] for a in applied], ['global-plan'])
        content = f.state()['global_plan']['content']
        self.assertEqual((content['case_owners'], content['requirement_owners']), ({cid: ['M010'] for cid in CASES}, {'R1': ['M010']}))

    def test_from_registration_to_the_leaves_plans_takes_one_go_and_one_mo_turn(self):
        """The top of a run walked by its cursor: what is left to a model is registering the root and confirming the cut."""
        self.doCleanups(); self.setUp(covered=False); f = self.f
        mo = {'role': 'module-orchestrator', 'instance_id': 'module-orchestrator'}
        turns = [('global-orchestrator', 'register')]  # in setUp
        for _ in range(10):
            ledger.advance_run(f.root, mo)
            for step in f.state()['next_steps']:
                ledger.advance(f.root, mo, step['module_id'])
            st = f.state()
            leaves = [s for s in st['next_steps'] if s['module_id'] in st['modules']]
            if leaves and all(s.get('operation') == 'plan' for s in leaves):
                break
            g = st['global_next_step']
            self.assertFalse(g.get('ready') and g.get('operation') and not g.get('mechanical'), g)  # no GO turn after registering
            step = next(s for s in st['next_steps'] if s.get('operation') == 'decompose')
            draft = read_json(Path(split_draft.write(f.root, step['module_id'], f.base / 'staging/module-orchestrator/draft')['draft']['path']))
            for n, child in enumerate(draft['children']):
                child['write_paths'] = [str(f.target / ('leaf%d' % n))]
            f.call('decompose', {'plan_ref': f.ref('walk-split.json', draft)}, module=step['module_id'])
            turns.append(('module-orchestrator', 'decompose'))
        self.assertEqual(turns, [('global-orchestrator', 'register'), ('module-orchestrator', 'decompose')])
        self.assertEqual(len([m for m in f.state()['modules'] if m != 'M010']), 2)

    def test_the_drafted_split_is_accepted_and_coverage_carried(self):
        f = self.f
        out = split_draft.write(f.root, 'M010', f.base / 'staging/module-orchestrator/draft')
        draft = read_json(Path(out['draft']['path']))
        for n, child in enumerate(draft['children']):  # the orchestrator narrows each leaf's write paths
            child['write_paths'] = [str(f.target / ('leaf%d' % n))]
        f.call('decompose', {'plan_ref': f.ref('split.json', draft)}, module='M010')
        s = f.state()
        self.assertIn('M010', s['module_groups'])  # accepted in the same event: no GO accept step
        self.assertEqual(sorted(sorted(m['case_ids']) for m in s['modules'].values()), [CASES[:3], CASES[3:]])
        self.assertEqual(s['global_plan']['carried_over'], 'M010')  # nor a GO coverage step
        self.assertEqual(sorted(s['global_plan']['content']['case_owners'][CASES[0]]), [m for m in s['modules'] if CASES[0] in s['modules'][m]['case_ids']])
        workflow.planning_guard(s, next(iter(s['modules'])))
        self.assertEqual({step['operation'] for step in s['next_steps'] if step.get('module_id') in s['modules']}, {'plan'})

    def test_a_split_other_than_the_draft_still_waits_for_the_go(self):
        f = self.f
        draft = read_json(Path(split_draft.write(f.root, 'M010', f.base / 'staging/module-orchestrator/draft')['draft']['path']))
        draft['children'][0]['case_ids'], draft['children'][1]['case_ids'] = CASES[:2], CASES[2:]  # cut elsewhere than drafted
        for n, child in enumerate(draft['children']):
            child['write_paths'] = [str(f.target / ('leaf%d' % n))]
        try:
            f.call('decompose', {'plan_ref': f.ref('other-split.json', draft)}, module='M010')
        except Exception:
            return  # the hand cut breaks a slicing rule: refused, nothing accepted
        self.assertNotIn('M010', f.state().get('module_groups', {}))


if __name__ == '__main__':
    unittest.main()
