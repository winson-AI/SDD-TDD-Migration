"""Parameters are written to the target by a tool and used by key: the Spec states only exceptions, acceptance regenerates and compares."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from contracts import Rejected, check_ref, file_ref, read_json
from lean_tools import collect_ui_sources
import ledger
import lean_worker
import migration_report
import parameter_file
import parameter_fixture
import project_context as pc
import test_project_context
import ui_parameters

APPROVED = 'the title is one size larger on the target'


class ParameterFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.target = self.root / 'target'; self.target.mkdir()
        self.args = parameter_fixture.build(self.root / 'android')
        self.index = collect_ui_sources.collect(self.args)
        self.rules = parameter_file.convention({
            'file': str(self.target / 'gen/Params{module}.kt'), 'header': 'object P{module} {\n', 'footer': '}\n',
            'lines': {'dimension': '    val {key} = {value}f // {unit}', 'dimension:sp': '    val {key} = {value}.sp', 'number': '    val {key} = {value}',
                      'color': '    val {key} = 0x{argb}', 'string': '    const val {key} = {quoted}'},
            'accessor': 'P{module}.{key}', 'locales': {'zh': str(self.target / 'gen/Params{module}_zh.kt')}, 'string_escapes': {'$': '\\$'}}, self.target)
        proof = self.root / 'constant-review.txt'; proof.write_text('Synthetic fixture source evaluation resolves to 1')
        self.fill = {'tokens': [{'token': 'Palette.ink', 'value': {'type': 'color', 'value': '#FF222222'}},
                                {'token': 'Fonts.bold', 'accessor': 'AppFonts.bold'}],
                     'settled': [{'id': 'code:Home/title.alpha', 'value': {'type': 'number', 'value': 1},
                                  'constant_reason': 'Source evaluation reviewed for this fixture', 'constant_evidence_refs': [file_ref(proof)]}]}

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value))
        return path

    def analysis(self, fill=None, rules='project', sheet=True):
        index_ref = file_ref(self.write('index.json', self.index))
        ui = {'dimension': 'UI', 'status': 'applicable', 'items': [{'item_id': 'UI-1', 'semantic_model': {'ui_evidence': {'source_index_ref': index_ref}}}]}
        analysis = {'module_id': 'M001', 'dimensions': [ui]}
        if sheet:
            document = ui_parameters.derive(analysis, self.rules if rules == 'project' else rules)
            ui['parameter_sheet_ref'] = file_ref(self.write('sheet.json', document))
        fill = self.fill if fill is None else fill
        if fill:
            ui['parameter_fill'] = fill
        return analysis

    def state(self, **over):
        return {'target_root': str(self.target), 'target_resources': {'parameters': self.rules}, **over}

    def gate(self, analysis=None, alternatives=(APPROVED,), **state):
        analysis = copy.deepcopy(analysis or self.analysis())
        # These numeric-sheet fixtures exclude layout structure; dedicated tests bind it to behavior.
        ui = analysis['dimensions'][0]
        if ui.get('parameter_sheet_ref'):
            ids = [p['id'] for p in ui_parameters.parameters(analysis) if p['class'] == 'keyword']
            ui.setdefault('parameter_fill', {}).setdefault('not_applicable', []).append(
                {'ids': ids, 'reason': 'Numeric-sheet fixture; layout structure is validated separately'})
        parameter_file.gate(self.state(**state), {'decision_envelope': {'allowed_alternatives': list(alternatives)}}, analysis)

    def decided(self, fill=None):
        analysis = self.analysis(fill)
        return parameter_file.decisions(ui_parameters.parameters(analysis), parameter_file.declarations(analysis), [APPROVED])

    # ------------------------------------------------------------------ the convention

    def test_the_shipped_convention_template_is_accepted_and_writes_a_file(self):
        text = (Path(__file__).resolve().parents[3] / 'template' / 'target-resources.json').read_text(encoding='utf-8')
        for name, value in (('{{absolute-target-root}}', str(self.target)), ('{{resource-directory}}', 'resources'), ('{{source-directory}}', 'src')):
            text = text.replace(name, value)
        self.assertNotIn('{{', text)
        rules = pc.target_resources(json.loads(text)['target_resources'], self.target)
        self.assertEqual(set(rules), {'copy', 'parameters'})
        analysis = self.analysis(rules=rules['parameters'])
        files, accessors = parameter_file.render(ui_parameters.load(analysis), parameter_file.declarations(analysis))
        (path, body), = files.items()
        self.assertEqual(path, str(self.target / 'src/M001/LegacyParameters.kt'))
        self.assertTrue(body.startswith('// Generated') and 'object LegacyParametersM001 {' in body and body.endswith('}\n'))
        self.assertTrue(accessors and all(name.startswith('LegacyParametersM001.') or name == 'AppFonts.bold' for name in accessors))

    def test_the_convention_is_one_file_per_module_a_line_per_type_and_the_way_code_names_a_key(self):
        self.assertTrue(self.rules['file'].endswith('gen/Params{module}.kt'))
        base = {'file': str(self.target / 'P{module}.kt'), 'lines': dict(self.rules['lines']), 'accessor': 'P.{key}'}
        parameter_file.convention(base, self.target)
        for over, message in (({'file': str(self.target / 'P.kt')}, 'contains {module}'), ({'file': 'P{module}.kt'}, 'absolute file path'),
                              ({'file': str(self.root / 'outside/P{module}.kt')}, 'inside target_root'),
                              ({'lines': {'dimension': '{key}'}}, 'needs a line template for dimension, number, color and string'),
                              ({'lines': {**base['lines'], 'shadow': '{key}'}}, 'needs a line template'),
                              ({'lines': {**base['lines'], 'number': '{key} {name}'}}, 'may use only'), ({'accessor': 'P.{id}'}, 'may use only'),
                              ({'locales': {'zh': str(self.target / 'zh.kt')}}, 'contains {module}'), ({'mode': 'x'}, 'takes file, header')):
            with self.subTest(over=over), self.assertRaisesRegex(Rejected, message):
                parameter_file.convention({**base, **over}, self.target)

    # ------------------------------------------------------------------ what a Spec decides

    def test_every_value_is_used_as_recorded_unless_the_spec_states_an_exception(self):
        decided = self.decided()
        self.assertEqual(decided['code:Home/title.textSize'], {'status': 'used', 'value': {'type': 'dimension', 'value': 20, 'unit': 'dp'}})
        self.assertEqual(decided['code:Home/title.alpha'], {'status': 'settled', 'value': {'type': 'number', 'value': 1}})
        self.assertEqual(decided['code:Home/title.textColor']['status'], 'mapped')
        self.assertEqual(decided['code:Home/title.typeface'], {'status': 'mapped', 'token': 'Fonts.bold', 'accessor': 'AppFonts.bold'})
        self.assertEqual(decided['layout:home/title.text']['status'], 'linked')
        self.assertEqual(decided['layout:home/LinearLayout1.orientation']['status'], 'structural')
        self.assertEqual(decided['layout:home/LinearLayout1.ImageView1.src']['status'], 'picture')
        self.assertEqual(decided['layout:home/LinearLayout1.background']['status'], 'layer')

    def test_a_parameter_that_does_not_apply_is_named_by_id_owner_or_attribute_with_a_reason(self):
        fill = {**self.fill, 'not_applicable': [
            {'ids': ['code:Home/badge.alpha'], 'reason': 'the badge is not migrated'},
            {'owner': 'code:Home.Legacy/footer', 'reason': 'a retired screen'},
            {'name': 'contentDescription', 'reason': 'accessibility labels are a later module'}]}
        decided = self.decided(fill)
        for pid in ('code:Home/badge.alpha', 'code:Home.Legacy/footer.textSize', 'layout:home/LinearLayout1.ImageView1.contentDescription'):
            self.assertEqual(decided[pid]['status'], 'not-applicable', pid)
        for row, message in (({'ids': ['code:Home/badge.alpha']}, 'needs a reason'), ({'reason': 'x'}, 'needs a reason and ids, an owner or a name'),
                             ({'ids': ['code:Home/ghost.alpha'], 'reason': 'x'}, 'names no recorded parameter'),
                             ({'owner': 'code:Nowhere/view', 'reason': 'x'}, 'names no recorded parameter')):
            with self.subTest(row=row), self.assertRaisesRegex(Rejected, message):
                self.decided({**self.fill, 'not_applicable': [row]})

    def test_a_deviation_gives_another_value_and_names_an_alternative_a_human_approved(self):
        row = {'id': 'code:Home/title.textSize', 'value': {'type': 'dimension', 'value': 22, 'unit': 'dp'}, 'alternative': APPROVED, 'reason': 'matches the target type scale'}
        self.assertEqual(self.decided({**self.fill, 'deviations': [row]})['code:Home/title.textSize'],
                         {'status': 'deviation', 'value': {'type': 'dimension', 'value': 22, 'unit': 'dp'}})
        for over, message in (({'alternative': 'looks fine'}, 'allowed_alternatives'), ({'reason': ' '}, 'needs a reason'),
                              ({'value': {'type': 'dimension', 'value': 22}}, 'needs a typed value'), ({'id': 'code:Home/title.alpha'}, 'names a recorded value parameter')):
            with self.subTest(over=over), self.assertRaisesRegex(Rejected, message):
                self.decided({**self.fill, 'deviations': [{**row, **over}]})
        with self.assertRaisesRegex(Rejected, 'not applicable or decided, not both'):
            self.decided({**self.fill, 'deviations': [row], 'not_applicable': [{'ids': [row['id']], 'reason': 'x'}]})

    def test_a_token_is_given_a_value_or_an_existing_accessor_and_an_expression_a_value(self):
        for fill, message in (({'tokens': [{'token': 'Palette.ink'}]}, 'a value or the accessor'),
                              ({'tokens': [{'token': 'Palette.ink', 'value': {'type': 'color', 'value': '#fff'}, 'accessor': 'T.ink'}]}, 'a value or the accessor'),
                              ({'tokens': [{'token': 'Palette.gone', 'accessor': 'T.ink'}]}, 'names one token the sheet holds'),
                              ({'settled': [{'id': 'code:Home/title.textSize', 'value': {'type': 'number', 'value': 1}}]}, 'names a recorded expression'),
                              ({'settled': [{'id': 'code:Home/title.alpha', 'value': {'type': 'keyword', 'value': 'x'}}]}, 'needs a typed value'),
                              ({'unknown': []}, 'parameter_fill takes'), ({'tokens': {}}, 'is a list of records')):
            with self.subTest(fill=fill), self.assertRaisesRegex(Rejected, message):
                self.decided(fill)

    # ------------------------------------------------------------------ freeze

    def test_freeze_needs_every_expression_settled_and_every_token_mapped(self):
        self.gate()
        with self.assertRaisesRegex(Rejected, 'expressions the Spec must settle or mark not applicable: code:Home/title.alpha'):
            self.gate(self.analysis({'tokens': self.fill['tokens']}))
        with self.assertRaisesRegex(Rejected, 'tokens the Spec must map or mark not applicable: Fonts.bold, Palette.ink'):
            self.gate(self.analysis({'settled': self.fill['settled']}))
        skipped = {'settled': self.fill['settled'], 'not_applicable': [{'name': 'textColor', 'reason': 'theme colours come later'},
                                                                         {'name': 'typeface', 'reason': 'theme fonts come later'}]}
        self.gate(self.analysis(skipped))

    def test_freeze_holds_the_sheet_to_its_evidence_the_project_convention_and_the_approved_plan(self):
        analysis = self.analysis()
        document = read_json(check_ref(analysis['dimensions'][0]['parameter_sheet_ref']))
        document['parameters'][0]['value'] = 999
        analysis['dimensions'][0]['parameter_sheet_ref'] = file_ref(self.write('sheet.json', document))
        with self.assertRaisesRegex(Rejected, 'differs from the one its UI evidence gives'):
            self.gate(analysis)
        with self.assertRaisesRegex(Rejected, 'another target parameter convention'):
            self.gate(self.analysis(rules=None))
        with self.assertRaisesRegex(Rejected, 'another target parameter convention'):
            self.gate(target_resources={})
        deviation = {'id': 'code:Home/title.textSize', 'value': {'type': 'dimension', 'value': 22, 'unit': 'dp'}, 'alternative': APPROVED, 'reason': 'type scale'}
        self.gate(self.analysis({**self.fill, 'deviations': [deviation]}))
        with self.assertRaisesRegex(Rejected, 'allowed_alternatives'):
            self.gate(self.analysis({**self.fill, 'deviations': [deviation]}), alternatives=())

    def test_a_project_that_states_the_convention_gets_a_sheet_from_every_module_with_ui(self):
        with self.assertRaisesRegex(Rejected, 'a module with UI names its parameter_sheet_ref'):
            self.gate(self.analysis(fill={}, sheet=False))
        parameter_file.gate({'target_resources': {}}, {}, self.analysis(fill={}, sheet=False))  # no convention, no obligation
        with self.assertRaisesRegex(Rejected, 'parameter_fill needs a parameter_sheet_ref'):
            parameter_file.gate({'target_resources': {}}, {}, self.analysis(sheet=False))

    # ------------------------------------------------------------------ the generated file and its acceptance

    def rendered(self, fill=None):
        analysis = self.analysis(fill)
        return analysis, *parameter_file.render(ui_parameters.load(analysis), parameter_file.declarations(analysis))

    def test_the_file_is_determined_by_the_sheet_the_decisions_and_the_templates(self):
        _, files, accessors = self.rendered()
        main = files[str(self.target / 'gen/ParamsM001.kt')]
        self.assertTrue(main.startswith('object PM001 {\n') and main.endswith('}\n'))
        for line in ('    val code_Home_title_textSize = 20f // dp', '    val values_dimen_title_size = 18.sp', '    val layout_home_title_maxLines = 2',
                     '    val values_color_brand = 0xFF3390EC', '    const val values_string_home_title = "Home"', '    val code_Home_title_alpha = 1',
                     '    val token_Palette_ink = 0xFF222222', '    const val layout_home_LinearLayout1_ImageView1_contentDescription = "Back"'):
            self.assertIn(line + '\n', main)
        self.assertNotIn('paddingTop', main)      # structure is not a value
        self.assertNotIn('title_text ', main)     # a link is satisfied by what it links to
        self.assertEqual(files[str(self.target / 'gen/ParamsM001_zh.kt')], 'object PM001 {\n    const val values_string_home_title = "首页"\n}\n')
        self.assertIn('PM001.code_Home_title_textSize', accessors)
        self.assertIn('AppFonts.bold', accessors)  # a token mapped to an existing target value is used by that name
        self.assertEqual(self.rendered()[1], files)  # the same inputs give the same bytes

    def test_a_deviation_and_a_string_escape_change_what_is_written(self):
        values = self.root / 'android/app/src/main/res/values/values.xml'
        values.write_text(values.read_text().replace('>Home<', '>Home $1 "now"<'))
        self.index = collect_ui_sources.collect(self.args)
        deviation = {'id': 'code:Home/title.textSize', 'value': {'type': 'dimension', 'value': 22, 'unit': 'dp'}, 'alternative': APPROVED, 'reason': 'type scale'}
        _, files, _ = self.rendered({**self.fill, 'deviations': [deviation], 'not_applicable': [{'ids': ['code:Home/badge.alpha'], 'reason': 'no badge'}]})
        main = files[str(self.target / 'gen/ParamsM001.kt')]
        self.assertIn('    val code_Home_title_textSize = 22f // dp\n', main)
        self.assertIn('    const val values_string_home_title = "Home \\$1 \\"now\\""\n', main)
        self.assertNotIn('badge_alpha', main)

    def synced(self, fill=None):
        analysis, files, accessors = self.rendered(fill)
        for path, text in files.items():
            Path(path).parent.mkdir(parents=True, exist_ok=True); Path(path).write_text(text, encoding='utf-8')
        screen = self.target / 'Home.kt'
        screen.write_text('\n'.join('use(%s)' % accessor for accessor in accessors))
        return analysis, [file_ref(screen)] + [file_ref(path) for path in files], screen, accessors

    def test_acceptance_regenerates_the_file_and_looks_for_every_key_in_the_code(self):
        analysis, code, screen, accessors = self.synced()
        parameter_file.verify(analysis, code)
        generated = self.target / 'gen/ParamsM001.kt'
        original = generated.read_text()
        generated.write_text(original.replace('= 20f', '= 24f'))
        with self.assertRaisesRegex(Rejected, 'generated parameter file is missing or was edited'):
            parameter_file.verify(analysis, code)
        generated.unlink()
        with self.assertRaisesRegex(Rejected, 'generated parameter file is missing or was edited'):
            parameter_file.verify_files(analysis)
        generated.write_text(original)
        screen.write_text(screen.read_text().replace('use(PM001.code_Home_title_textSize)\n', ''))
        with self.assertRaisesRegex(Rejected, r'1 recorded parameters are not used by the submitted code: PM001.code_Home_title_textSize'):
            parameter_file.verify(analysis, [file_ref(screen)] + code[1:])

    def test_a_key_is_used_only_when_the_code_names_exactly_it(self):
        self.assertTrue(parameter_file.named('x = P.badge_alpha + 1', 'P.badge_alpha'))
        self.assertFalse(parameter_file.named('x = P.badge_alpha_2', 'P.badge_alpha'))
        self.assertFalse(parameter_file.named('x = XP.badge_alpha', 'P.badge_alpha'))
        analysis, code, screen, accessors = self.synced()
        longer = next(a for a in accessors if a.endswith('paddingLeft'))
        screen.write_text(screen.read_text().replace('use(%s)' % longer, 'use(%s_dp)' % longer))
        with self.assertRaisesRegex(Rejected, 'not used by the submitted code: ' + longer.replace('.', r'\.')):
            parameter_file.verify(analysis, [file_ref(screen)] + code[1:])

    def test_the_generated_file_does_not_count_as_the_code_that_uses_it(self):
        analysis, code, screen, _ = self.synced()
        with self.assertRaisesRegex(Rejected, 'recorded parameters are not used by the submitted code'):
            parameter_file.verify(analysis, code[1:])

    def test_the_summary_gives_the_fill_rate_and_the_report_shows_it(self):
        fill = {**self.fill, 'not_applicable': [{'owner': 'code:Home.Legacy/footer', 'reason': 'a retired screen'}]}
        summary = parameter_file.summary(self.analysis(fill))
        counts = summary['counts']
        self.assertEqual((counts['not-applicable'], counts['settled'], counts['mapped']), (1, 1, 2))
        owed = sum(counts.get(k, 0) for k in ('used', 'deviation', 'settled', 'mapped', 'not-applicable'))
        self.assertEqual(summary['fill_rate'], round((counts['used'] + counts['mapped']) / owed, 4))
        self.assertEqual((summary['components'], summary['layers']), (6, 2))
        ref = file_ref(self.write('analysis.json', self.analysis(fill)))
        state = {'modules': {'M001': {'plan': {'dimension_analysis_ref': ref, 'paths': []}}}}
        pictures = migration_report.fidelity(state, [], check_ref)[2]
        self.assertEqual(pictures['parameters']['M001'], summary)
        text = migration_report.render({'run_id': 'r1', 'sequence': 1, 'report_stage': 'in-progress', 'quality': 'yellow-blocked', 'entry_mode': 'project',
                                        'single_module_id': None, 'case_counts': {}, 'legacy_root': '/l', 'target_root': '/t', 'parent_mo_names': {},
                                        'cases': [], 'paths': [], 'non_green': [], 'human_report': None, 'picture_fidelity': pictures})
        self.assertIn('| M001 | 6 / 2 | %d | %d | 1 | 0 | %s |' % (summary['parameters'], counts['used'] + counts['mapped'], summary['fill_rate']), text)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.f = test_project_context.ProjectContextTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.rules = {'file': str(self.f.target / 'app/gen/P{module}.kt'), 'header': 'object P{module} {\n', 'footer': '}\n', 'accessor': 'P{module}.{key}',
                      'lines': {'dimension': '  val {key} = {value}', 'number': '  val {key} = {value}', 'color': '  val {key} = 0x{argb}', 'string': '  val {key} = {quoted}'}}
        pc.update(self.f.root, self.f.request('resources', 1, {'target_resources': {'parameters': self.rules}}), self.f.actor)
        self.f.start(self.f.init_payload(self.f.prepare()))
        self.state, self.events = ledger.read_events(self.f.run)
        parameter_fixture.build(self.f.legacy)
        self.sequence = 0

    def run_worker(self, operation, actor, **args):
        self.sequence += 1
        request = {'request_id': 'request-' + str(self.sequence), 'operation': operation, 'module_id': 'M001',
                   'assignment_id': 'I1', 'fencing_token': 'token-1', 'args': args}
        with patch.object(lean_worker.ledger, 'read_events', return_value=(self.state, self.events)), \
                patch.object(lean_worker, 'verify_plan', return_value=None):
            return read_json(check_ref(lean_worker.run(self.f.run, request, actor)['result_ref']))

    def test_the_plan_operation_derives_the_sheet_and_the_sync_operation_writes_the_file(self):
        spec = {'role': 'spec-designer', 'instance_id': 'spec-1'}
        index_ref = self.run_worker('analyze-ui', spec, scope='home', source_files=['Home.kt'], layouts=['home'],
                                    layout_helpers=parameter_fixture.HELPERS)['source_index_ref']
        analysis = {'module_id': 'M001', 'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'UI-1', 'semantic_model': {'ui_evidence': {'source_index_ref': index_ref}}}]}]}
        path = self.f.run / 'staging/analysis.json'; path.write_text(json.dumps(analysis))
        planned = self.run_worker('resource-plan', spec, dimension_analysis_ref=file_ref(path))
        self.assertNotIn('copy_plan_ref', planned)  # this project states no copy convention
        self.assertEqual(planned['parameters']['tokens'], ['Fonts.bold', 'Palette.ink'])
        document = read_json(check_ref(planned['parameter_sheet_ref']))
        self.assertEqual((document['module_id'], document['convention']['accessor']), ('M001', 'P{module}.{key}'))
        analysis['dimensions'][0].update(parameter_sheet_ref=planned['parameter_sheet_ref'], parameter_fill={
            'tokens': [{'token': 'Palette.ink', 'accessor': 'T.ink'}, {'token': 'Fonts.bold', 'accessor': 'T.bold'}],
            'not_applicable': [{'ids': ['code:Home/title.alpha'], 'reason': 'always visible on the target'}]})
        path.write_text(json.dumps(analysis))
        worker = {'role': 'implementer', 'instance_id': 'worker-1'}
        task = {'assignment_id': 'I1', 'role': 'implementer', 'instance_id': 'worker-1', 'fencing_token': 'token-1', 'freeze_id': 'F1', 'closed': False,
                'execution_contract': {'task_ids': ['T1', 'T2'], 'path_ids': []}}
        self.state['modules'] = {'M001': {'module_id': 'M001', 'phase': 'implementing', 'freeze_id': 'F1', 'write_paths': [str(self.f.target / 'app')],
            'assignments': {'I1': task}, 'plan': {'definitions': [], 'paths': [], 'dimension_analysis_ref': file_ref(path),
                                                   'tasks': [{'task_id': 'T1', 'scope': {'write_paths': [str(self.f.target / 'app/screens')]}},
                                                             {'task_id': 'T2', 'scope': {'write_paths': [str(self.f.target / 'app/gen')]}}]}}}
        with self.assertRaisesRegex(Rejected, 'generated parameter file outside the assigned write scope'):
            self.run_worker('resource-sync', worker, task_id='T1')
        synced = self.run_worker('resource-sync', worker, task_id='T2')
        generated = self.f.target / 'app/gen/PM001.kt'
        self.assertEqual(synced['parameter_files'], [file_ref(generated)])
        self.assertIn('  val code_Home_title_textSize = 20\n', generated.read_text())
        self.assertGreater(synced['keys'], 10)
        parameter_file.verify_files(analysis)

    def test_layout_helpers_are_declared_as_a_call_and_what_each_argument_gives(self):
        spec = {'role': 'spec-designer', 'instance_id': 'spec-1'}
        for helpers in ([{'call': 'frame'}], [{'call': 'frame', 'params': []}], [{'call': 'frame', 'params': ['layout_width'], 'unit': 'em'}], 'frame'):
            with self.subTest(helpers=helpers), self.assertRaisesRegex(Rejected, 'layout_helpers rows need'):
                self.run_worker('analyze-ui', spec, scope='home', source_files=['Home.kt'], layout_helpers=helpers)


if __name__ == '__main__':
    unittest.main()
