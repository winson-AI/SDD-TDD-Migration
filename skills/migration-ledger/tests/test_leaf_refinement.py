"""A leaf works from its allocation and adds what only it can produce: its plan may bind a refinement of the allocated
analysis that keeps everything the allocation states."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import dimensions
import ledger
from contracts import Rejected, check_ref, read_json
import test_dimensions

PROOF = {'path': '/source.md', 'sha256': 'a'}
ALLOCATED = {
    'module_id': 'M001', 'parent_ref': None, 'unresolved': [], 'scope': {'in': ['sign in'], 'out': ['orders'], 'requirement_ids': ['R1']},
    'dimensions': [
        {'dimension': 'UI', 'status': 'applicable', 'reason': 'one screen', 'parameter_sheet_ref': None, 'evidence_refs': [PROOF], 'items': [
            {'item_id': 'SCREEN', 'behavior': 'shows the form', 'acceptance': 'same fields', 'requirement_ids': ['R1'], 'case_ids': ['C1'],
             'evidence_refs': [PROOF], 'semantic_model': {'kind': 'ui-tree'},
             'fidelity_conditions': [{'condition_id': 'FONT', 'condition': 'fixed sizes', 'status': 'applicable', 'reason': 'legacy uses dp',
                                      'evidence_refs': [PROOF], 'assertions': []}]}]},
        {'dimension': 'Logic', 'status': 'not-applicable', 'reason': 'no rule', 'evidence_refs': [PROOF], 'items': []}]}


class KeepsTests(unittest.TestCase):
    def refined(self, change):
        value = copy.deepcopy(ALLOCATED); change(value)
        return value

    def item(self, value):
        return value['dimensions'][0]['items'][0]

    def test_a_refinement_adds_what_only_the_leaf_can_produce(self):
        added = (
            lambda v: self.item(v).update(resource_strategy='copied as it is'),                         # a new field
            lambda v: self.item(v)['semantic_model'].update(ui_evidence={'ui_tree_ref': PROOF}),        # inside what the allocation started
            lambda v: self.item(v)['evidence_refs'].append({'path': '/leaf-review.md', 'sha256': 'b'}),  # more evidence
            lambda v: self.item(v)['fidelity_conditions'][0]['assertions'].append({'path_id': 'P1', 'assertion_id': 'A1'}),
            lambda v: v['dimensions'][0].update(parameter_sheet_ref=PROOF),                              # a field the allocation left empty
            lambda v: v.update(leaf_notes='read the whole screen'),
        )
        for change in added:
            dimensions.keeps(ALLOCATED, self.refined(change))
        dimensions.keeps(ALLOCATED, copy.deepcopy(ALLOCATED))

    def test_it_changes_or_drops_nothing_the_allocation_states(self):
        refused = (
            (lambda v: self.item(v).update(acceptance='something easier'), r'changes analysis\.dimensions\[UI\]\.items\[SCREEN\]\.acceptance'),
            (lambda v: self.item(v).pop('behavior'), r'drops analysis\.dimensions\[UI\]\.items\[SCREEN\]\.behavior'),
            (lambda v: self.item(v)['evidence_refs'].clear(), 'drops entries of'),
            (lambda v: self.item(v)['case_ids'].append('C2'), r'changes .*case_ids'),
            (lambda v: self.item(v)['fidelity_conditions'][0].update(status='not-applicable'), r'changes .*\[FONT\]\.status'),
            (lambda v: self.item(v)['fidelity_conditions'].clear(), 'adds, drops or reorders'),
            (lambda v: v['dimensions'][0]['items'].append({'item_id': 'EXTRA'}), 'adds, drops or reorders'),  # new work is allocated, not assumed
            (lambda v: v['dimensions'][1].update(status='applicable'), r'changes analysis\.dimensions\[Logic\]\.status'),
            (lambda v: v['dimensions'][1]['items'].append({'item_id': 'RULE'}), r'changes analysis\.dimensions\[Logic\]\.items'),
            (lambda v: v['dimensions'].reverse(), 'adds, drops or reorders analysis.dimensions'),
            (lambda v: v['unresolved'].append('is the checkbox shown?'), r'changes analysis\.unresolved'),
            (lambda v: v['scope']['out'].clear(), r'changes analysis\.scope\.out'),
        )
        for change, message in refused:
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                dimensions.keeps(ALLOCATED, self.refined(change))


class RefinedPlanTests(unittest.TestCase):
    def setUp(self):
        self.d = d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        self.f = f = d.f
        d.root(); f.split(d.proposal())
        self.held = f.state()['modules']['M001']['dimension_analysis_ref']

    def refined(self, change=None, name='M001-refined.json'):
        analysis = read_json(check_ref(self.held))
        analysis['dimensions'][1]['items'][0]['leaf_review'] = 'read the handler and its two callers'
        if change: change(analysis)
        return self.f.ref(name, analysis)

    def plan(self, ref):
        plan = self.d.leaf_plan()
        plan['dimension_analysis_ref'] = ref
        return plan

    def submit(self, plan, name='refined-plan.json'):
        self.f.call('plan', {'plan_ref': self.f.ref(name, plan)}, role='spec-designer')

    def test_a_plan_binds_the_refinement_and_the_allocation_stays_what_was_registered(self):
        ref = self.refined()
        self.submit(self.plan(ref))
        module = self.f.state()['modules']['M001']
        self.assertEqual((module['plan']['dimension_analysis_ref'], module['dimension_analysis_ref']), (ref, self.held))
        self.assertEqual(dimensions.of_leaf(module), ref)  # what its gates, workers and report read from now on
        self.assertEqual(dimensions.of_leaf({'dimension_analysis_ref': self.held}), self.held)  # a leaf without a plan works from its allocation

    def test_a_refinement_that_changes_the_allocation_is_not_one(self):
        easier = lambda analysis: analysis['dimensions'][1]['items'][0].update(acceptance='something easier to verify')
        with self.assertRaisesRegex(Rejected, 'refined analysis changes'):
            self.submit(self.plan(self.refined(easier, 'M001-easier.json')))
        self.assertIsNone(self.f.state()['modules']['M001']['plan'])
        self.assertFalse(dimensions.refines(self.held, self.refined(easier, 'M001-easier-again.json')))
        self.assertTrue(dimensions.refines(self.held, self.refined()))

    def test_what_the_leaf_adds_is_judged_like_a_registered_analysis(self):
        broken = lambda analysis: analysis['dimensions'][1]['items'][0].update(semantic_model={'kind': 'no-such-model'})
        with self.assertRaises(Rejected):
            self.submit(self.plan(self.refined(broken, 'M001-broken-model.json')))
        self.assertIsNone(self.f.state()['modules']['M001']['plan'])

    def test_the_first_freeze_on_a_refinement_judges_that_refinement(self):
        module = {'dimension_analysis_ref': self.held, 'plan': {'dimension_analysis_ref': self.refined()}, 'freeze_id': None, 'planning_history': []}
        self.assertFalse(ledger.allocation_frozen(module))
        self.assertTrue(ledger.allocation_frozen({**module, 'freeze_id': 'F1'}))
        earlier = {'freeze_id': 'F0', 'plan': {'dimension_analysis_ref': self.held}}  # frozen before on the bare allocation
        self.assertFalse(ledger.allocation_frozen({**module, 'planning_history': [earlier]}))


class TemplateTests(unittest.TestCase):
    """A leaf refines the file it was allocated; only a leaf with a screen is handed the model template for its evidence."""
    def names(self, analysis):
        import reading
        import tempfile, json, hashlib
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        path = Path(directory.name).resolve() / 'analysis.json'; path.write_text(json.dumps(analysis))
        module = {'dimension_analysis_ref': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
        return {name.split('/')[-1] for name in reading.templates({}, module, {'role': 'spec-designer', 'operation': 'plan'})}

    def test_the_model_template_follows_the_screen(self):
        row = lambda dimension, status: {'dimension': dimension, 'status': status, 'items': [{'item_id': dimension}] if status == 'applicable' else []}
        with_screen = self.names({'dimensions': [row('UI', 'applicable'), row('Logic', 'applicable')]})
        without = self.names({'dimensions': [row('UI', 'not-applicable'), row('Logic', 'applicable')]})
        self.assertIn('semantic-model.json', with_screen)
        self.assertNotIn('semantic-model.json', without)
        self.assertFalse({'dimension-analysis.json'} & (with_screen | without))  # it copies its allocation and adds to it


if __name__ == '__main__':
    unittest.main()
