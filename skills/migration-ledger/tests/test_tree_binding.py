"""The slices and the cases come from one feature inventory: a functional leaf is one or more nodes of the feature tree,
accepts exactly their cases, and over a supplied test summary anchors on the cases the user gave."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import workflow
from contracts import Rejected, file_ref

CASES = ['C%d' % n for n in range(1, 11)]


def feature(fid, path, cases, evidence=()):
    return {'feature_id': fid, 'name': fid, 'functional_path': path, 'trigger': 'tap', 'observable_result': 'shown',
            'requirement_ids': ['R1'], 'case_ids': list(cases), 'evidence_refs': list(evidence)}


def tree(evidence=()):
    return [feature('F-PHONE-ENTER', 'Login/Phone/Enter', ['C1', 'C2'], evidence), feature('F-PHONE-SEND', 'Login/Phone/Send', ['C3', 'C4'], evidence),
            feature('F-CODE-ENTER', 'Login/Code/Enter', ['C5', 'C6', 'C7'], evidence), feature('F-CODE-RESEND', 'Login/Code/Resend', ['C8'], evidence),
            feature('F-INTRO', 'Login/Intro', ['C9', 'C10'], evidence)]


SUPPLIED = ['F-PHONE-ENTER', 'F-PHONE-SEND', 'F-CODE-ENTER']


def leaf(mid, cases, *paths, kind=None):
    return {'module_id': mid, 'case_ids': list(cases), 'dependencies': [], **({'kind': kind} if kind else {}),
            **({'functional_paths': list(paths)} if paths else {})}


class TreeBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.n = 0
        self.s = {'modules': {}, 'module_groups': {}, 'dimension_slicing_required': False}
        self.parent = {'module_id': 'M001', 'case_ids': list(CASES)}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        self.n += 1
        p = Path(self.tmp.name) / ('%d-%s' % (self.n, name))
        p.write_text(content if isinstance(content, str) else json.dumps(content))
        return file_ref(p)

    def inventory(self, summary=False, **extra):
        units = [{'unit_id': 'U1', 'kind': 'test-case-group', 'locator': 'cases', 'feature_ids': SUPPLIED}] if summary else []
        return self.write('inventory.json', {'features': tree(), 'source_units': units,
                                             'test_summary_ref': self.write('cases.md', 'supplied cases') if summary else None, **extra})

    def judge(self, children, ref, record=True, s=None):
        decomposition.standard(s or self.s, self.parent, children, {'feature_inventory_ref': ref} if ref else {}, record=record)

    def test_a_leaf_is_one_or_more_nodes_of_the_tree_and_accepts_their_cases(self):
        ref = self.inventory()
        phone, rest = leaf('M002', CASES[:4], 'Login/Phone'), leaf('M003', CASES[4:], 'Login/Code', 'Login/Intro')  # a subtree; two nodes
        self.judge([phone, rest], ref)
        self.judge([phone, rest, leaf('M004', ['C1'], kind='scaffold')], ref)  # a scaffold holds no node; its cases are what it serves
        with self.assertRaisesRegex(Rejected, 'accepts exactly the cases of the features it holds'):
            self.judge([leaf('M002', CASES[:3], 'Login/Phone'), leaf('M003', CASES[3:], 'Login/Code', 'Login/Intro')], ref)
        with self.assertRaisesRegex(Rejected, 'feature F-PHONE-SEND is held by M002 and M003: leaves do not overlap'):
            self.judge([phone, leaf('M003', CASES[2:], 'Login/Phone/Send', 'Login/Code', 'Login/Intro')], ref)
        with self.assertRaisesRegex(Rejected, 'features without a leaf: F-INTRO'):
            self.judge([phone, leaf('M003', CASES[4:8], 'Login/Code')], ref)
        with self.assertRaisesRegex(Rejected, 'names its feature-tree nodes: functional_paths'):
            self.judge([leaf('M002', CASES[:4]), rest], ref)
        with self.assertRaisesRegex(Rejected, 'M002 names no feature of the parent'):
            self.judge([leaf('M002', CASES[:4], 'Login/Avatar'), rest], ref)
        with self.assertRaisesRegex(Rejected, 'a scaffold holds no feature-tree node'):
            self.judge([phone, rest, leaf('M004', ['C1'], 'Login/Phone', kind='scaffold')], ref)

    def test_a_fresh_split_under_readiness_names_its_inventory(self):
        s = {**self.s, 'context_readiness_required': True}
        with self.assertRaisesRegex(Rejected, 'names the feature inventory it cuts'):
            self.judge([leaf('M002', CASES[:4]), leaf('M003', CASES[4:])], None, s=s)
        held = leaf('M002', CASES[:4])
        s['modules'] = {'M002': dict(held)}  # a re-split that restates a registered leaf is judged as it was accepted
        self.judge([held, leaf('M003', CASES[4:])], None, s=s)
        self.judge([leaf('M002', CASES[:4]), leaf('M003', CASES[4:])], None)  # the minimal API without an inventory

    def test_over_a_supplied_summary_a_leaf_anchors_on_supplied_cases_and_its_derived_features_are_a_fact(self):
        ref = self.inventory(summary=True)
        phone = leaf('M002', CASES[:4], 'Login/Phone')
        with self.assertRaisesRegex(Rejected, 'M004 holds only features derived from source'):
            self.judge([phone, leaf('M003', CASES[4:7], 'Login/Code/Enter'), leaf('M004', CASES[7:], 'Login/Code/Resend', 'Login/Intro')], ref)
        self.judge([phone, leaf('M003', CASES[4:], 'Login/Code', 'Login/Intro')], ref)
        fact = self.s['issues']['SLICE-M003-derived']
        self.assertEqual((fact['kind'], fact['applies_to'], fact['resolved']['M001']['recorded']), ('fact', ['M001'], True))
        self.assertIn('2 features found in source beyond the supplied cases: F-CODE-RESEND, F-INTRO', fact['summary'])
        self.assertNotIn('SLICE-M002-derived', self.s['issues'])
        s = {'modules': {}, 'module_groups': {}, 'dimension_slicing_required': False}
        self.judge([phone, leaf('M003', CASES[4:], 'Login/Code', 'Login/Intro')], ref, record=False, s=s)
        self.assertNotIn('issues', s)

    def test_the_global_plan_names_the_leaf_a_feature_tree_node_gave_as_its_only_owner(self):
        evidence = self.write('discovery.md', 'reviewed')
        legacy = str(Path(self.tmp.name) / 'legacy')
        inventory = self.write('inventory.json', {
            'schema_version': 1, 'legacy_root': legacy, 'entry_mode': 'project', 'single_module_id': None, 'source_mode': 'legacy-source',
            'test_summary_ref': None, 'features': tree([evidence]),
            'source_units': [{'unit_id': 'U1', 'kind': 'legacy-entry', 'locator': legacy, 'feature_ids': [f['feature_id'] for f in tree()], 'evidence_refs': [evidence]}],
            'coverage': {'status': 'complete', 'unclassified': [], 'unresolved_questions': []}, 'questions': []})
        s = {'legacy_root': legacy, 'entry_mode': 'project', 'requirement_ids': ['R1'], 'case_ids': list(CASES), 'context_readiness_required': True,
             'modules': {'M002': {'case_ids': CASES[:4], 'functional_paths': ['Login/Phone']},
                         'M003': {'case_ids': CASES[4:], 'functional_paths': ['Login/Code', 'Login/Intro']}}}
        owners = {'F-PHONE-ENTER': ['M002'], 'F-PHONE-SEND': ['M002'], 'F-CODE-ENTER': ['M003'], 'F-CODE-RESEND': ['M003'], 'F-INTRO': ['M003']}
        plan = {'feature_inventory_ref': inventory, 'feature_owners': owners, 'requirement_owners': {'R1': ['M002', 'M003']},
                'case_owners': {cid: ['M002'] for cid in CASES[:4]} | {cid: ['M003'] for cid in CASES[4:]}, 'boundary_review': {'issues': []}}
        workflow.feature_inventory(s, plan)
        shared = {**plan, 'feature_owners': {**owners, 'F-INTRO': ['M002', 'M003']}, 'case_owners': {**plan['case_owners'], 'C9': ['M002', 'M003'], 'C10': ['M002', 'M003']}}
        with self.assertRaisesRegex(Rejected, 'feature F-INTRO is held by M003: feature_owners names that leaf alone'):
            workflow.feature_inventory(s, shared)
        stale = {**s, 'modules': {**s['modules'], 'M003': {'case_ids': CASES[4:9], 'functional_paths': ['Login/Code', 'Login/Intro']}}}
        with self.assertRaisesRegex(Rejected, 'M003 was cut from an earlier inventory'):
            workflow.feature_inventory(stale, plan)


if __name__ == '__main__':
    unittest.main()
