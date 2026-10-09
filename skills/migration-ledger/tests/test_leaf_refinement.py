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


class ConsumerTests(unittest.TestCase):
    """An allocation is written before its leaf reads the source: it may name only the directory whose code will consume
    a resource. The leaf names the files; a result is then held to exactly those."""
    ALLOCATED = {'dimensions': [{'dimension': 'Resource', 'status': 'applicable', 'items': [
        {'item_id': 'ICONS', 'source_resource': '@drawable/ic_back', 'consumer': ['/t/ui/phone', '/t/res/Fonts.kt#Bold']}]}]}

    def refined(self, consumer, allocated=None):
        value = copy.deepcopy(allocated or self.ALLOCATED)
        value['dimensions'][0]['items'][0]['consumer'] = consumer
        return value

    def test_a_leaf_names_the_files_in_the_directory_its_allocation_gave(self):
        for consumer in (['/t/ui/phone/PhoneScreen.kt#Arrow', '/t/res/Fonts.kt#Bold'],
                         ['/t/ui/phone/PhoneScreen.kt', '/t/ui/phone/parts/Row.kt', '/t/res/Fonts.kt#Bold'],
                         ['/t/ui/phone', '/t/res/Fonts.kt#Bold']):  # the allocation as it is
            dimensions.keeps(self.ALLOCATED, self.refined(consumer))
        single = self.refined('/t/ui/phone')  # one consumer written as a string
        dimensions.keeps(single, self.refined(['/t/ui/phone/PhoneScreen.kt'], single))

    def test_a_file_the_allocation_names_stays_and_nothing_is_consumed_outside_it(self):
        refused = (
            (['/t/ui/phone/PhoneScreen.kt'], r'changes .*\[ICONS\]\.consumer'),                           # drops the file it named
            (['/t/ui/phone/PhoneScreen.kt', '/t/res/Other.kt#Bold'], r'changes .*\.consumer'),             # replaces it
            (['/t/res/Fonts.kt#Bold'], r'changes .*\.consumer'),                                           # leaves the directory without a file
            (['/t/ui/phone/parts', '/t/res/Fonts.kt#Bold'], r'changes .*\.consumer'),                       # a narrower directory is not a file
            (['/t/ui/phone/PhoneScreen.kt', '/t/res/Fonts.kt#Bold', '/t/ui/code/CodeScreen.kt'], 'adds a consumer outside'),
            ([], r'changes .*\.consumer'),
        )
        for consumer, message in refused:
            with self.subTest(consumer=consumer), self.assertRaisesRegex(Rejected, message):
                dimensions.keeps(self.ALLOCATED, self.refined(consumer))


class DetailTests(unittest.TestCase):
    """A leaf details an allocated Resource item into items of its own, one per file or drawing its evidence finds."""
    ALLOCATED = {'dimensions': [
        {'dimension': 'Logic', 'status': 'applicable', 'items': [{'item_id': 'RULE', 'requirement_ids': ['R1'], 'case_ids': ['C1']}]},
        {'dimension': 'Resource', 'status': 'applicable', 'items': [
            {'item_id': 'ICONS', 'source_resource': 'the icons of the screen', 'requirement_ids': ['R1', 'R2'], 'case_ids': ['C1', 'C2'],
             'parent_item_ids': ['ROOT-RES']}]}]}
    DETAIL = {'item_id': 'ICONS.back', 'detail_of': 'ICONS', 'source_resource': '@drawable/ic_back', 'requirement_ids': ['R1'], 'case_ids': ['C2']}

    def refined(self, *details, dimension=1, change=None):
        value = copy.deepcopy(self.ALLOCATED)
        value['dimensions'][dimension]['items'].extend(copy.deepcopy(list(details)))
        if change: change(value)
        return value

    def test_a_detail_item_names_what_it_details_and_stays_inside_it(self):
        dimensions.keeps(self.ALLOCATED, self.refined(self.DETAIL))
        dimensions.keeps(self.ALLOCATED, self.refined(self.DETAIL, {**self.DETAIL, 'item_id': 'ICONS.search', 'parent_item_ids': ['ROOT-RES']}))
        refused = (
            ({**self.DETAIL, 'item_id': 'back'}, 'carries its identifier as a prefix'),
            ({**self.DETAIL, 'item_id': 'ICONS.'}, 'carries its identifier as a prefix'),
            ({**self.DETAIL, 'detail_of': 'ELSEWHERE'}, 'names the allocated Resource item it details'),
            ({**self.DETAIL, 'requirement_ids': ['R3']}, 'stays inside the requirements, cases and parent items'),
            ({**self.DETAIL, 'case_ids': ['C1', 'C9']}, 'stays inside the requirements, cases and parent items'),
            ({**self.DETAIL, 'parent_item_ids': ['ANOTHER-ROOT-ITEM']}, 'stays inside the requirements, cases and parent items'),
        )
        for detail, message in refused:
            with self.subTest(detail=detail), self.assertRaisesRegex(Rejected, message):
                dimensions.keeps(self.ALLOCATED, self.refined(detail))

    def test_the_allocated_items_stay_and_nothing_else_is_added(self):
        plain = {key: value for key, value in self.DETAIL.items() if key != 'detail_of'}
        with self.assertRaisesRegex(Rejected, 'adds, drops or reorders'):  # an item that details nothing is new work
            dimensions.keeps(self.ALLOCATED, self.refined(plain))
        with self.assertRaisesRegex(Rejected, 'adds, drops or reorders'):
            dimensions.keeps(self.ALLOCATED, self.refined(self.DETAIL, change=lambda v: v['dimensions'][1]['items'].pop(0)))
        with self.assertRaisesRegex(Rejected, r'changes analysis\.dimensions\[Resource\]\.items\[ICONS\]\.source_resource'):
            dimensions.keeps(self.ALLOCATED, self.refined(self.DETAIL, change=lambda v: v['dimensions'][1]['items'][0].update(source_resource='@drawable/ic_back')))
        with self.assertRaisesRegex(Rejected, 'adds, drops or reorders'):  # only resources are detailed this way
            dimensions.keeps(self.ALLOCATED, self.refined({'item_id': 'RULE.more', 'detail_of': 'RULE', 'requirement_ids': ['R1'], 'case_ids': ['C1']}, dimension=0))

    def test_a_plan_traces_the_detail_item_like_any_other(self):
        d = test_dimensions.DimensionTests(); d.setUp(); self.addCleanup(d.doCleanups)
        f = d.f
        d.root(('Logic', 'Resource')); f.split(d.proposal(('Logic', 'Resource')))
        held = f.state()['modules']['M001']['dimension_analysis_ref']
        analysis = read_json(check_ref(held))
        resource = analysis['dimensions'][3]['items']
        detail = {**copy.deepcopy(resource[0]), 'item_id': resource[0]['item_id'] + '.badge', 'detail_of': resource[0]['item_id'],
                  'source_resource': 'legacy/badge.svg', 'target_resource': str(f.target / 'm1/badge.svg')}
        resource.append(detail)
        plan = d.leaf_plan()
        plan['dimension_analysis_ref'] = f.ref('M001-detailed.json', analysis)
        with self.assertRaisesRegex(Rejected, 'SPEC dimension trace must cover every allocated item'):  # the leaf owes what it added
            f.call('plan', {'plan_ref': f.ref('untraced-detail.json', plan)}, role='spec-designer')
        plan['dimension_trace'].append({'item_id': detail['item_id'], 'task_ids': ['T1'], 'path_ids': ['P1'],
                                        'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}]})
        for task in plan['tasks']:
            task['dimension_analysis']['dimensions'][3]['item_ids'].append(detail['item_id'])
        for definition in plan['definitions']:
            if definition['kind'] in ('design', 'spec', 'tasks'):
                path = check_ref(definition); path.write_text(path.read_text() + '\nDetail: ' + detail['item_id'] + '\n')
                from contracts import file_ref
                definition.update(file_ref(path))
        f.call('plan', {'plan_ref': f.ref('traced-detail.json', plan)}, role='spec-designer')
        module = f.state()['modules']['M001']
        self.assertEqual(module['dimension_analysis_ref'], held)
        self.assertIn(detail['item_id'], [row['item_id'] for row in module['plan']['dimension_trace']])


if __name__ == '__main__':
    unittest.main()
