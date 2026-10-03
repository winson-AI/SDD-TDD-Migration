"""File resources reach the target by path: the plan is derived, the copy is mechanical, acceptance compares bytes and names."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, check_ref, file_ref, read_json
import dimensions
import ledger
import lean_worker
import migration_report
import project_context as pc
import resource_copy
import resource_fidelity as rf
import ui_fidelity
import test_dimensions
import test_project_context
import test_resource_signal_closure as closure

ANIMATION = json.dumps({'v': '5.7', 'fr': 30, 'ip': 0, 'op': 60, 'w': 120, 'h': 120, 'layers': [{}]})
PNG = b'\x89PNG\r\n\x1a\n'


class CopyPlanTests(unittest.TestCase):
    def setUp(self):
        self.c = closure.SignalClosureTests('test_drawables_nested_in_a_declared_drawable_must_be_covered')
        self.c.setUp(); self.addCleanup(self.c.doCleanups)
        self.s, self.n, self.f = self.c.s, self.c.n, self.c.f
        self.c.write('res/drawable-xhdpi/ic_back.webp', b'RIFF-xhdpi')
        self.c.write('res/drawable-xxhdpi/ic_back.webp', b'RIFF-xxhdpi')
        self.c.write('res/drawable/ic_star.xml', closure.VECTOR % '')
        self.c.write('res/raw/loading.json', ANIMATION)
        self.c.write('res/drawable/bubble.9.png', PNG + b'nine')
        self.c.write('assets/hero.png', PNG + b'hero')
        self.c.declare('@drawable/ic_back', '@drawable/ic_star', '@raw/loading', '@drawable/bubble')
        self.c.code('\nfun icons() {\n  bar.setNavIcon(R.drawable.ic_back)\n  star.show(R.drawable.ic_star)\n  wait.play(R.raw.loading)\n'
                    '  box.frame(R.drawable.bubble)\n  hero.load("file:///android_asset/hero.png")\n}\n')
        self.rules = {'root': str(self.n.target / 'res'), 'path': '{kind}/{name}{ext}', 'accessor': 'Res.{kind}.{name}',
                      'formats': ['webp', 'png', 'vector-xml', 'animation-json']}
        title = self.f.analysis['dimensions'][3]['items'][0]   # the fixture's string item moves into this target tree
        title.update(target_resource=str(self.n.target / 'res/values/strings.xml') + '#Res.string.settings_title',
                     consumer=[str(self.n.target / 'Screen.kt') + '#Title'])
        bubble = next(s for s in rf.skeletons(self.c.index(), self.c.tree())['resources'] if s['source_resource'] == '@drawable/bubble')
        self.bubble = self.c.item_for(bubble, resource_strategy='compose_semantic_exact', nine_patch=True,
                                      target_resource=str(self.n.target / 'Bubble.kt') + '#BubbleFrame')
        self.f.analysis['dimensions'][3]['items'].append(self.bubble)

    def plan(self, rules=None):
        return resource_copy.derive(self.f.analysis, rules or self.rules)

    def adopt(self, plan=None):
        plan = plan or self.plan()[0]
        self.f.analysis['dimensions'][3]['copy_plan_ref'] = file_ref(self.n.write('evidence/copy-plan.json', plan))
        return plan

    def state(self, **over):
        return {**self.f.state, 'legacy_root': str(self.n.android), 'target_root': str(self.n.target),
                'target_resources': {'copy': resource_copy.convention(self.rules)}, **over}

    def freeze(self, **over):
        module, state = self.f.module(), self.state(**over)
        module['plan']['decision_envelope'] = {'allowed_alternatives': []}
        ui_fidelity.freeze_gate(state, module)
        rf.freeze_gate(state, module)
        return module

    def rows(self):
        return {row['source_resource']: row for row in self.plan()[0]['rows']}

    # ------------------------------------------------------------------ the plan follows from the records and the convention

    def test_every_file_resource_the_target_loads_gets_a_row_with_its_path_and_name(self):
        plan, authored = self.plan()
        rows = {row['source_resource']: row for row in plan['rows']}
        self.assertEqual(sorted(rows), ['@drawable/ic_back', '@drawable/ic_star', '@raw/loading', 'asset:hero.png'])
        back = rows['@drawable/ic_back']
        self.assertEqual((back['qualifier'], back['variant'], back['format']), ('xxhdpi', 'base', 'webp'))
        self.assertEqual(back['source_ref'], file_ref(self.n.android / 'app/src/main/res/drawable-xxhdpi/ic_back.webp'))
        self.assertEqual(Path(back['target_path']), (self.n.target / 'res/drawable/ic_back.webp').resolve())
        self.assertEqual(back['accessor'], 'Res.drawable.ic_back')
        self.assertEqual(back['used_by'], ['node:settings.root'])
        self.assertEqual((rows['@drawable/ic_star']['format'], rows['@raw/loading']['format']), ('vector-xml', 'animation-json'))
        self.assertEqual(rows['asset:hero.png']['accessor'], 'Res.asset.hero')
        self.assertEqual(authored, [{'source_resource': '@drawable/bubble', 'variant': 'base',
                                     'reason': 'the target does not load nine-patch as it is'}])

    def test_the_project_states_which_formats_load_and_which_density_is_taken(self):
        rows = {row['source_resource']: row for row in self.plan({**self.rules, 'formats': ['webp'], 'density': ['xhdpi']})[0]['rows']}
        self.assertEqual(sorted(rows), ['@drawable/ic_back'])
        self.assertEqual(rows['@drawable/ic_back']['qualifier'], 'xhdpi')
        _, authored = self.plan({**self.rules, 'formats': ['webp']})
        self.assertIn({'source_resource': '@drawable/ic_star', 'variant': 'base', 'reason': 'the target does not load vector-xml as it is'}, authored)

    def test_the_convention_is_a_root_in_the_target_two_templates_and_the_formats(self):
        resource_copy.convention(self.rules, self.n.target)
        for over, message in (({'root': 'res'}, 'absolute directory'), ({'root': str(self.n.android)}, 'inside target_root'),
                              ({'path': '{kind}/fixed.png'}, 'contains {name}'), ({'path': '../{name}{ext}'}, 'relative path'),
                              ({'path': '{folder}/{name}'}, 'may use only'), ({'accessor': 'Res.{id}'}, 'may use only'),
                              ({'accessor': ''}, 'template string'), ({'formats': []}, 'formats lists'), ({'formats': ['png', 'png']}, 'formats lists'),
                              ({'density': 'xxhdpi'}, 'ordered list'), ({'mode': 'flat'}, 'takes root, path')):
            with self.subTest(over=over), self.assertRaisesRegex(Rejected, message):
                resource_copy.convention({**self.rules, **over}, self.n.target)

    def test_two_resources_cannot_land_on_one_target_file(self):
        self.c.write('res/drawable/loading.xml', closure.VECTOR % '')
        self.c.declare('@drawable/loading')
        self.c.code('\nfun twice() = R.drawable.loading\n')
        self.plan()  # kind and suffix keep the two apart
        with self.assertRaisesRegex(Rejected, r'several resources map to one target file.*@drawable/loading / base, @raw/loading / base'):
            self.plan({**self.rules, 'path': 'flat/{name}'})

    # ------------------------------------------------------------------ a row stands where an authored item would

    def test_rows_cover_their_resources_so_only_the_rest_is_authored(self):
        with self.assertRaisesRegex(Rejected, 'uncovered presentation refs'):
            self.freeze()
        self.adopt()
        self.freeze()

    def test_a_resource_is_covered_once_by_a_row_or_by_an_item(self):
        self.adopt()
        skeleton = next(s for s in rf.skeletons(self.c.index(), self.c.tree())['resources'] if s['source_resource'] == '@drawable/ic_star')
        self.f.analysis['dimensions'][3]['items'].append(self.c.item_for(skeleton, target_resource=str(self.n.target / 'res/ic_star.xml') + '#Res.drawable.ic_star'))
        with self.assertRaisesRegex(Rejected, 'closure requires one item for @drawable/ic_star / base'):
            self.freeze()

    def test_the_ledger_recomputes_the_plan_so_a_row_cannot_be_edited_dropped_or_added(self):
        plan = self.plan()[0]
        for change, message in ((lambda p: p['rows'][0].update(target_path=str(self.n.target / 'elsewhere.webp')), 'differs from the one its UI evidence gives'),
                                (lambda p: p['rows'][0].update(accessor='Icons.Back'), 'differs from the one its UI evidence gives'),
                                (lambda p: p['rows'].append({**p['rows'][0], 'source_resource': '@drawable/ghost'}), 'differs from the one its UI evidence gives'),
                                (lambda p: p['convention'].update(accessor='R.{name}'), 'another target resource convention'),
                                (lambda p: p.update(producer='by-hand'), 'derived resource copy plan')):
            edited = copy.deepcopy(plan); change(edited)
            self.adopt(edited)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.freeze()
        dropped = copy.deepcopy(plan); dropped['rows'].pop()
        self.adopt(dropped)
        with self.assertRaisesRegex(Rejected, 'uncovered presentation refs|closure requires one item|differs from the one'):
            self.freeze()
        self.adopt(plan)
        with self.assertRaisesRegex(Rejected, 'needs the project to state target_resources.copy'):
            self.freeze(target_resources={})

    def test_a_changed_legacy_file_stales_the_plan(self):
        self.adopt()
        (self.n.android / 'app/src/main/res/raw/loading.json').write_text(ANIMATION.replace('60', '90'))
        with self.assertRaises(Rejected):
            self.freeze()

    # ------------------------------------------------------------------ the copy and its acceptance

    def synced(self):
        self.adopt()
        copies = resource_copy.sync(self.f.analysis, lambda path: path.is_relative_to(self.n.target))
        for row, target, payload, action in copies:
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
        screen = self.n.write('target/Screen.kt', 'val nav = Res.drawable.ic_back; val s = Res.drawable.ic_star\n'
                                                  'val w = Res.raw.loading; val h = Res.asset.hero\n')
        return copies, [file_ref(screen)] + [file_ref(target) for _, target, _, _ in copies]

    def test_sync_copies_the_legacy_bytes_keeps_identical_files_and_never_overwrites_others(self):
        copies, _ = self.synced()
        self.assertEqual([action for *_, action in copies], ['copied'] * 4)
        self.assertEqual((self.n.target / 'res/drawable/ic_back.webp').read_bytes(), b'RIFF-xxhdpi')
        again = resource_copy.sync(self.f.analysis, lambda path: False)   # nothing left to write, so no scope is needed
        self.assertEqual([action for *_, action in again], ['kept'] * 4)
        (self.n.target / 'res/drawable/ic_back.webp').write_bytes(b'redrawn')
        with self.assertRaisesRegex(Rejected, 'already differs from the legacy resource'):
            resource_copy.sync(self.f.analysis, lambda path: True)
        (self.n.target / 'res/drawable/ic_back.webp').unlink()
        with self.assertRaisesRegex(Rejected, 'outside the assigned write scope'):
            resource_copy.sync(self.f.analysis, lambda path: False)

    def test_acceptance_compares_every_copy_with_the_legacy_file_and_looks_for_its_name_in_the_code(self):
        _, code = self.synced()
        resource_copy.verify(self.f.analysis, code)
        screen = Path(code[0]['path'])
        screen.write_text(screen.read_text().replace('Res.raw.loading', 'StaticSpinner'))
        with self.assertRaisesRegex(Rejected, r'not named by the submitted code: @raw/loading \(Res.raw.loading\)'):
            resource_copy.verify(self.f.analysis, [file_ref(screen)] + code[1:])
        star = self.n.target / 'res/drawable/ic_star.xml'
        star.write_text('<vector/>')
        with self.assertRaisesRegex(Rejected, 'missing or is not the legacy file: @drawable/ic_star'):
            resource_copy.verify(self.f.analysis, code)
        star.unlink()
        with self.assertRaisesRegex(Rejected, 'missing or is not the legacy file: @drawable/ic_star'):
            resource_copy.verify_files(self.f.analysis)

    def test_a_copy_does_not_count_as_the_code_that_names_it(self):
        self.adopt()
        for row, target, payload, _ in resource_copy.sync(self.f.analysis, lambda path: True):
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(payload)
        named_inside_a_copy = [file_ref(self.n.target / 'res/drawable/ic_star.xml')]
        with self.assertRaisesRegex(Rejected, 'not named by the submitted code'):
            resource_copy.verify(self.f.analysis, named_inside_a_copy)

    def test_the_report_counts_what_was_copied(self):
        self.adopt()
        ref = file_ref(self.n.write('evidence/analysis.json', self.f.analysis))
        state = {'modules': {'M001': {'plan': {'dimension_analysis_ref': ref, 'paths': []}}}}
        _, _, pictures = migration_report.fidelity(state, [], check_ref)
        self.assertEqual(pictures['copied'], 4)
        text = migration_report.render({**BLANK_REPORT, 'picture_fidelity': pictures})
        self.assertIn('按路径复制到目标的文件资源：4 个', text)


BLANK_REPORT = {'run_id': 'r1', 'sequence': 1, 'report_stage': 'in-progress', 'quality': 'yellow-blocked', 'entry_mode': 'project',
                'single_module_id': None, 'case_counts': {}, 'legacy_root': '/legacy', 'target_root': '/target', 'parent_mo_names': {},
                'cases': [], 'paths': [], 'non_green': [], 'human_report': None}


class ConventionFlowTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.rules = {'root': str(self.f.target / 'assets'), 'path': '{name}{ext}', 'accessor': 'assets/{path}', 'formats': ['png', 'webp']}

    def test_the_convention_is_project_configuration_frozen_into_the_run_and_shown_to_planners(self):
        pc.update(self.f.root, self.f.request('resources', 1, {'target_resources': {'copy': self.rules}}), self.f.actor)
        prepared = self.f.prepare()
        frozen = prepared['input']['target_resources']['copy']
        self.assertEqual((frozen['root'], frozen['density']), (str((self.f.target / 'assets').resolve()), []))
        pc.update(self.f.root, self.f.request('other', 2, {'target_resources': {'copy': {'accessor': 'img/{name}'}}}), self.f.actor)
        self.f.start(self.f.init_payload(prepared))
        status = ledger.status(self.f.run)
        self.assertEqual(status['planning_context']['target_resources'], {'copy': frozen})
        with self.assertRaisesRegex(Rejected, 'target resources mismatch'):
            pc.bind_run(prepared['project_context_ref'], self.f.run, 'r1',
                        {**self.f.init_payload(prepared), 'target_resources': {'copy': {**frozen, 'accessor': 'x/{name}'}}})

    def test_a_convention_outside_the_target_or_with_unknown_fields_is_refused(self):
        for patch_value, message in (({'copy': {**self.rules, 'root': str(self.f.legacy / 'res')}}, 'inside target_root'),
                                     ({'copy': {**self.rules, 'path': '{nope}'}}, 'may use only'), ({'paste': {}}, 'target_resources takes copy')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                pc.update(self.f.root, self.f.request('bad', 1, {'target_resources': patch_value}), self.f.actor)

    def test_a_run_without_a_convention_has_none(self):
        prepared = self.f.prepare()
        self.assertNotIn('target_resources', prepared['input'])
        self.f.start(self.f.init_payload(prepared))
        self.assertNotIn('target_resources', ledger.status(self.f.run)['planning_context'])


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.target / 'app/assets'
        pc.update(self.f.root, self.f.request('resources', 1, {'target_resources': {'copy': {
            'root': str(self.root), 'path': '{name}{ext}', 'accessor': 'assets/{path}', 'formats': ['png']}}}), self.f.actor)
        self.f.start(self.f.init_payload(self.f.prepare()))
        self.state, self.events = ledger.read_events(self.f.run)
        icon = self.f.legacy / 'app/src/main/res/drawable-xxhdpi/ic_back.png'
        icon.parent.mkdir(parents=True); icon.write_bytes(PNG + b'back')
        source = self.f.legacy / 'app/src/main/java/demo/Home.kt'
        source.parent.mkdir(parents=True); source.write_text('class Home { fun build() { bar.setNavIcon(R.drawable.ic_back) } }\n')
        self.sequence = 0

    def run_worker(self, operation, actor, **args):
        self.sequence += 1
        request = {'request_id': 'request-' + str(self.sequence), 'operation': operation, 'module_id': 'M001',
                   'assignment_id': 'I1', 'fencing_token': 'token-1', 'args': args}
        with patch.object(lean_worker.ledger, 'read_events', return_value=(self.state, self.events)), \
                patch.object(lean_worker, 'verify_plan', return_value=None):
            output = lean_worker.run(self.f.run, request, actor)
        return read_json(check_ref(output['result_ref']))

    def analysis(self, declared=True):
        spec = {'role': 'spec-designer', 'instance_id': 'spec-1'}
        index_ref = self.run_worker('analyze-ui', spec, scope='home', entry=['Home.kt'])['source_index_ref']
        tree = {'schemaVersion': 1, 'scope': 'home', 'screens': [{'id': 'screen:home', 'root': {
            'id': 'node:home.root', 'presentation': {'resourceRefs': ['@drawable/ic_back'] if declared else []}, 'dynamicRules': [], 'children': []}}]}
        tree_path = self.f.run / 'staging/tree.json'; tree_path.write_text(json.dumps(tree))
        analysis = {'dimensions': [
            {'dimension': 'UI', 'status': 'applicable', 'items': [{'item_id': 'UI-1', 'semantic_model': {
                'ui_evidence': {'source_index_ref': index_ref, 'ui_tree_ref': file_ref(tree_path), 'coverage': 'home:base:viewport'}}}]},
            {'dimension': 'Resource', 'status': 'applicable', 'items': []}]}
        path = self.f.run / 'staging/analysis.json'; path.write_text(json.dumps(analysis))
        return analysis, path

    def test_a_spec_designer_derives_the_plan_and_an_implementer_copies_it_inside_its_write_scope(self):
        analysis, path = self.analysis()
        spec = {'role': 'spec-designer', 'instance_id': 'spec-1'}
        planned = self.run_worker('resource-plan', spec, dimension_analysis_ref=file_ref(path))
        self.assertEqual((planned['status'], planned['rows'], planned['authored'], planned['undeclared']), ('PLANNED', 1, [], []))
        row = read_json(check_ref(planned['copy_plan_ref']))['rows'][0]
        self.assertEqual((Path(row['target_path']), row['accessor']), ((self.root / 'ic_back.png').resolve(), 'assets/ic_back.png'))
        analysis['dimensions'][1]['copy_plan_ref'] = planned['copy_plan_ref']
        path.write_text(json.dumps(analysis))
        worker = {'role': 'implementer', 'instance_id': 'worker-1'}
        task = {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'worker-1', 'fencing_token': 'token-1', 'freeze_id': 'F1', 'closed': False}
        module = {'module_id': 'M001', 'phase': 'implementing', 'freeze_id': 'F1', 'write_paths': [str(self.f.target / 'app')],
                  'assignments': {'I1': task}, 'plan': {'definitions': [], 'paths': [], 'dimension_analysis_ref': file_ref(path),
                                                         'tasks': [{'task_id': 'T1', 'scope': {'write_paths': [str(self.f.target / 'app/screens')]}},
                                                                   {'task_id': 'T2', 'scope': {'write_paths': [str(self.root)]}}]}}
        self.state['modules'] = {'M001': module}
        with self.assertRaisesRegex(Rejected, 'outside the assigned write scope'):
            self.run_worker('resource-sync', worker, task_id='T1')
        with self.assertRaisesRegex(Rejected, 'requires a frozen task_id'):
            self.run_worker('resource-sync', worker, task_id='T9')
        synced = self.run_worker('resource-sync', worker, task_id='T2')
        self.assertEqual([(r['action'], r['accessor']) for r in synced['rows']], [('copied', 'assets/ic_back.png')])
        self.assertEqual((self.root / 'ic_back.png').read_bytes(), PNG + b'back')
        self.assertEqual(self.run_worker('resource-sync', worker, task_id='T2')['rows'][0]['action'], 'kept')
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_worker('resource-sync', spec, task_id='T2')
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_worker('resource-plan', worker, dimension_analysis_ref=file_ref(path))

    def test_a_spec_designer_derives_the_image_checks_of_a_module_with_their_references(self):
        from PIL import Image
        Image.new('RGBA', (72, 72), (0, 0, 0, 255)).save(self.f.legacy / 'app/src/main/res/drawable-xxhdpi/ic_back.png')
        _, path = self.analysis()
        derived = self.run_worker('screen-checks', {'role': 'spec-designer', 'instance_id': 'spec-1'}, dimension_analysis_ref=file_ref(path))
        self.assertEqual((derived['status'], derived['checks'], derived['unrendered']), ('DERIVED', 1, []))
        check = read_json(check_ref(derived['screen_checks_ref']))['checks']['UI-1'][0]
        self.assertEqual((check['node_id'], check['source_resource'], check['target']), ('node:home.root', '@drawable/ic_back', {'selector': {'resource-id': 'home.root'}}))
        self.assertEqual(read_json(check_ref(check['reference']['render_ref']))['producer'], 'sdd-reference-render')
        with self.assertRaisesRegex(Rejected, 'outside role capability'):
            self.run_worker('screen-checks', {'role': 'implementer', 'instance_id': 'worker-1'}, dimension_analysis_ref=file_ref(path))

    def test_the_plan_operation_reports_what_the_tree_still_omits(self):
        _, path = self.analysis(declared=False)
        planned = self.run_worker('resource-plan', {'role': 'spec-designer', 'instance_id': 'spec-1'}, dimension_analysis_ref=file_ref(path))
        self.assertEqual(planned['rows'], 0)
        self.assertEqual([(u['ref'], u['sites'][0]['call']) for u in planned['undeclared']], [('@drawable/ic_back', 'setNavIcon')])


class AuthoredItemTests(unittest.TestCase):
    """A resource item that is not in the copy plan is held to the same two questions: is it the legacy thing, is it used."""

    def setUp(self):
        self.d = test_dimensions.DimensionTests('test_multiple_consumers_are_all_verified_and_remain_live')
        self.d.setUp(); self.addCleanup(self.d.doCleanups)
        self.f = self.d.f
        self.analysis = self.d.analysis('M001', ('Resource',))
        self.item = self.analysis['dimensions'][3]['items'][0]
        self.legacy = Path(self.f.ref('legacy/res/drawable/ic_back.png', 'LEGACY-BYTES')['path'])
        self.target = self.f.ref('target/m1/ic_back.png', 'LEGACY-BYTES')
        self.screen = self.f.ref('target/m1/Screen.kt', 'val back = Res.drawable.ic_back')
        self.item.update(source_resource='@drawable/ic_back', source_resource_ref=file_ref(self.legacy), qualifier='base', resource_kind='bitmap',
                         resource_strategy='byte_copy', target_resource=self.target['path'] + '#Res.drawable.ic_back',
                         consumer=[self.screen['path'] + '#Toolbar'])

    def accept(self, target=None, consumers=None):
        plan = {'module_id': 'M001', 'dimension_analysis_ref': self.f.ref('analysis.json', self.analysis),
                'dimension_trace': [{'item_id': self.item['item_id'], 'task_ids': ['T1']}], 'tasks': []}
        target = target or self.target
        trace = {'item_id': self.item['item_id'], 'task_ids': ['T1'], 'summary': 'icon migrated', 'evidence_refs': [target],
                 'target_resource_ref': target, 'consumer_refs': consumers or [self.screen]}
        dimensions.implementation(plan, {'dimension_evidence': [trace]})

    def test_a_byte_copy_is_accepted_only_as_the_legacy_bytes_named_by_its_consumer(self):
        self.accept()
        redrawn = self.f.ref('target/m1/ic_back.png', 'DRAWN-BY-HAND')
        with self.assertRaisesRegex(Rejected, 'byte_copy target is not the legacy file'):
            self.accept(target=redrawn)
        self.target = self.f.ref('target/m1/ic_back.png', 'LEGACY-BYTES')
        unused = self.f.ref('target/m1/Screen.kt', 'Canvas { drawPath(arrow) }')
        with self.assertRaisesRegex(Rejected, 'consumer Screen.kt never names Res.drawable.ic_back'):
            self.accept(consumers=[unused])

    def test_a_values_entry_is_accepted_only_as_the_legacy_entry(self):
        legacy = Path(self.f.ref('legacy/res/values/strings.xml', '<resources><string name="title">Settings</string></resources>')['path'])
        target = self.f.ref('target/m1/values/strings.xml', '<resources><string name="title">Settings</string></resources>')
        self.item.update(source_resource='@string/title', source_resource_ref=file_ref(legacy), resource_kind='string',
                         resource_strategy='value_xml_exact', target_resource=target['path'] + '#Res.string.title')
        self.screen = self.f.ref('target/m1/Screen.kt', 'Text(Res.string.title)')
        self.item['consumer'] = [self.screen['path'] + '#Title']
        self.target = target
        self.accept()
        for content, message in (('<resources><string name="title">Preferences</string></resources>', 'target values entry differs'),
                                 ('<resources><string name="other">Settings</string></resources>', 'lacks the legacy entry')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                self.accept(target=self.f.ref('target/m1/values/strings.xml', content))

    def test_a_vector_is_accepted_only_as_the_conversion_of_the_legacy_vector(self):
        from types import SimpleNamespace
        from lean_tools import resource_tool
        legacy = Path(self.f.ref('legacy/res/drawable/ic_star.xml', closure.VECTOR % '')['path'])
        converted = resource_tool.prepare_vector(SimpleNamespace(android_root=str(legacy.parents[2]), target_root=str(self.f.target),
            source=str(legacy), destination='m1/ic_star.xml', source_id='@drawable/ic_star', target_ref='Res.drawable.ic_star',
            consumer=['Screen'], resolve_ref=[], consumer_tint=None))['content']
        self.target = self.f.ref('target/m1/ic_star.xml', converted)
        self.screen = self.f.ref('target/m1/Screen.kt', 'Icon(Res.drawable.ic_star)')
        self.item.update(source_resource='@drawable/ic_star', source_resource_ref=file_ref(legacy), resource_kind='vector',
                         resource_strategy='exact_vector_xml', target_resource=self.target['path'] + '#Res.drawable.ic_star',
                         consumer=[self.screen['path'] + '#Star'])
        self.accept()
        with self.assertRaisesRegex(Rejected, 'not the conversion of the legacy vector'):
            self.accept(target=self.f.ref('target/m1/ic_star.xml', converted.replace('M0,0h24v24h-24z', 'M0,0h12v12h-12z')))

    def test_a_resource_dimension_may_hold_a_copy_plan_and_no_authored_item(self):
        plan = self.f.ref('copy-plan.json', {'schema_version': 1, 'producer': 'sdd-resource-plan', 'rows': []})
        analysis = self.d.analysis('M001', ('Logic', 'Resource'))
        analysis['dimensions'][3].update(items=[], copy_plan_ref=plan)
        _, items = dimensions.load(self.f.ref('copied.json', analysis), 'M001')
        self.assertEqual({item['dimension'] for item in items.values()}, {'Logic'})
        analysis['dimensions'][3].pop('copy_plan_ref')
        with self.assertRaises(Rejected):
            dimensions.load(self.f.ref('copied.json', analysis), 'M001')  # applicable work with nothing in it
        analysis['dimensions'][1]['copy_plan_ref'] = plan
        analysis['dimensions'][3]['copy_plan_ref'] = plan
        with self.assertRaisesRegex(Rejected, 'a copy plan belongs to an applicable Resource dimension'):
            dimensions.load(self.f.ref('copied.json', analysis), 'M001')

    def test_at_freeze_a_migrated_resource_lives_in_the_target_has_a_name_and_target_consumers(self):
        root = self.f.target
        rf.require_target_binding(self.item, root)
        note = self.f.ref('notes/design.md', '# the icon is drawn with paths')
        for over, message in (({'consumer': [note['path'] + '#FD-9']}, 'a consumer is a file of the target project, not a document about it'),
                              ({'target_resource': note['path'] + '#x'}, 'target_resource must be a file of the target project'),
                              ({'target_resource': self.target['path']}, 'needs #<the name consumers use for it>')):
            with self.subTest(over=over), self.assertRaisesRegex(Rejected, message):
                rf.require_target_binding({**self.item, **over}, root)
        rf.require_target_binding({**self.item, 'resource_strategy': 'blocked', 'consumer': [note['path']]}, root)  # a gap has no target yet
        rf.require_target_binding({**self.item, 'resource_strategy': 'manual_exact', 'target_resource': self.screen['path']}, root)


if __name__ == '__main__':
    unittest.main()
