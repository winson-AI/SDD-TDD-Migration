"""What the user showed of the legacy application: it enters the run with the project context, reaches the leaf of its
cases, stands as the visual baseline of a screen the legacy cannot preview, and is cited by a PATH or owed."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import decomposition
import ledger
import migration_report
import project_context as pc
import reference_media
import spec_skeleton
import test_project_context
import test_source_changes
import ui_fidelity
import visual_evidence
from contracts import Rejected, carrying, check_ref, file_ref


def media_row(base, name='login.png', **over):
    path = base / name; path.write_bytes(b'bytes-of-' + name.encode())
    return {'media_id': 'MEDIA-' + name.split('.')[0], 'kind': 'video' if name.endswith('.mp4') else 'screenshot', 'path': str(path),
            'case_ids': ['C1'], 'screen': 'login', 'note': 'the legacy login screen', **over}


class ProjectInputTests(unittest.TestCase):
    def test_media_is_validated_copied_and_hash_bound_like_the_documents(self):
        t = test_project_context.ProjectContextTests(); t.setUp(); self.addCleanup(t.doCleanups)
        for bad, message in ((media_row(t.base, kind='gif'), 'screenshot or video'), (media_row(t.base, case_ids=[]), 'names the case_ids'),
                             (media_row(t.base, path='login.png'), 'must be absolute'), (media_row(t.base, role='design'), 'role is one of'),
                             (media_row(t.base, extra=1), 'rows take')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                pc.update(t.root, t.request('bad', 1, {'reference_media': [bad]}), t.actor)
        with self.assertRaisesRegex(Rejected, 'unique media_id'):
            pc.update(t.root, t.request('dup', 1, {'reference_media': [media_row(t.base), media_row(t.base)]}), t.actor)
        shot, clip = media_row(t.base), media_row(t.base, 'flow.mp4')
        pc.update(t.root, t.request('media', 1, {'reference_media': [shot, clip]}), t.actor)
        result = t.prepare()
        rows = result['input']['project_sources']['reference_media']
        self.assertEqual([(r['media_id'], r['kind'], r['role'], r['case_ids']) for r in rows],
                         [('MEDIA-login', 'screenshot', 'legacy-baseline', ['C1']), ('MEDIA-flow', 'video', 'legacy-baseline', ['C1'])])
        Path(shot['path']).write_bytes(b'edited after prepare')  # the run keeps what it was given
        self.assertEqual(check_ref(rows[0]['ref']).read_bytes(), b'bytes-of-login.png')
        t.start(t.init_payload(result))
        s = ledger.status(t.run)
        self.assertEqual([r['media_id'] for r in reference_media.of_module(s, {'case_ids': ['C1']})], ['MEDIA-login', 'MEDIA-flow'])
        self.assertEqual(reference_media.of_module(s, {'case_ids': ['C2']}), [])


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.shot = self.ref('login.png', 'legacy login pixels'); self.clip = self.ref('flow.mp4', 'legacy login recording')
        self.other = self.ref('other.png', 'another picture'); self.third = self.ref('third.png', 'the screen of C3')
        rows = [{'media_id': 'MEDIA-login', 'kind': 'screenshot', 'role': 'legacy-baseline', 'screen': 'login', 'case_ids': ['C1'], 'ref': self.shot},
                {'media_id': 'MEDIA-flow', 'kind': 'video', 'role': 'legacy-baseline', 'screen': 'login', 'case_ids': ['C1', 'C2'], 'ref': self.clip},
                {'media_id': 'MEDIA-third', 'kind': 'screenshot', 'role': 'legacy-baseline', 'screen': 'third', 'case_ids': ['C3'], 'ref': self.third}]
        self.s = {'project_context_ref': self.ref('snapshot.json', {'source_refs': {'reference_media': rows}}), 'ui_fidelity_required': True, 'modules': {}}

    def ref(self, name, content):
        path = self.base / name; path.write_text(content if isinstance(content, str) else json.dumps(content)); return file_ref(path)

    def evidence(self, **over):
        return {'coverage': 'login:base:viewport', 'legacy_executable': False, 'visual_mode': 'user-reference', 'baseline_refs': [self.shot], **over}

    def analysis(self, evidence, cases=('C1',)):
        return {'dimensions': [{'dimension': 'UI', 'status': 'applicable', 'items': [
            {'item_id': 'M001-UI', 'case_ids': list(cases), 'semantic_model': {'kind': 'ui-component-spec', 'ui_evidence': evidence}}]}]}

    def visual(self, **over):
        return {'path_id': 'PV', 'kind': 'visual', 'case_id': 'C1', 'coverage': 'login:base:viewport', 'node_ids': ['node:root'], 'baseline_ref': self.shot, **over}

    def baseline_gate(self, evidence, paths, cases=('C1',)):
        with mock.patch.object(ui_fidelity, '_analysis', lambda m: self.analysis(evidence, cases)), mock.patch.object(ui_fidelity, 'visual_plan_gate', lambda a, v: None):
            ui_fidelity.baseline_gate(self.s, {'module_id': 'M001', 'case_ids': ['C1', 'C2'], 'plan': {'paths': paths}})

    def test_a_screen_the_user_showed_is_aligned_to_the_screenshot_and_not_left_source_only(self):
        self.baseline_gate(self.evidence(), [self.visual()])
        self.baseline_gate(self.evidence(visual_mode='source-only', baseline_refs=None), [], cases=('C2',))  # only a recording shows C2
        with self.assertRaisesRegex(Rejected, 'the user showed this screen'):
            self.baseline_gate(self.evidence(visual_mode='source-only', baseline_refs=None), [])
        with self.assertRaisesRegex(Rejected, 'reference screenshots of the cases'):
            self.baseline_gate(self.evidence(baseline_refs=[self.other]), [self.visual(baseline_ref=self.other)])
        with self.assertRaisesRegex(Rejected, 'the user showed C3: cite its reference screenshot'):
            self.baseline_gate(self.evidence(), [self.visual()], cases=('C1', 'C3'))  # the item shows C3 too: its screenshot is cited as well
        self.baseline_gate(self.evidence(baseline_refs=[self.shot, self.third]), [self.visual()], cases=('C1', 'C3'))
        with self.assertRaisesRegex(Rejected, 'needs a visual test path'):
            self.baseline_gate(self.evidence(), [])
        with self.assertRaisesRegex(Rejected, 'falls back to source-only'):
            self.baseline_gate(self.evidence(visual_mode='runtime'), [self.visual()])

    def test_the_visual_path_of_a_user_reference_target_cites_the_screenshot(self):
        tree = {'schemaVersion': 1, 'scope': 'migrate-login', 'generatedFrom': {'sourceIndex': 'ui-source-index.json', 'sourceIndexSha256': 'aa'},
                'screens': [{'id': 'screen:login', 'root': {'id': 'node:root', 'presentation': {'resourceRefs': []}}}],
                'layoutClosure': [], 'criticalLayoutContracts': [], 'unresolved': []}
        analysis = self.analysis(self.evidence(ui_tree_ref=self.ref('tree.json', tree)))
        with mock.patch.object(ui_fidelity.ue, 'validate_native_evidence', lambda evidence: tree):  # the tree contract itself is covered in test_ui_fidelity
            ui_fidelity.visual_plan_gate(analysis, [self.visual()])
            with self.assertRaisesRegex(Rejected, 'lack visual paths'):
                ui_fidelity.visual_plan_gate(analysis, [])
            with self.assertRaisesRegex(Rejected, 'baseline differs from frozen target'):
                ui_fidelity.visual_plan_gate(analysis, [self.visual(baseline_ref=self.other)])

    def test_a_path_cites_media_of_its_own_case_and_a_shown_case_nobody_cites_is_owed(self):
        auto = {'path_id': 'P1', 'kind': 'automation', 'case_id': 'C1'}
        analysis = self.ref('analysis.json', self.analysis(self.evidence()))
        plan = lambda *paths, **over: {'dimension_analysis_ref': analysis, 'paths': list(paths), **over}
        m = {'module_id': 'M001', 'case_ids': ['C1']}
        reference_media.plan_gate(self.s, m, plan({**auto, 'reference_media_ids': ['MEDIA-flow']}, self.visual()))
        for bad, message in (({**auto, 'reference_media_ids': ['MEDIA-nope']}, 'name the run reference media'),
                             ({**auto, 'reference_media_ids': ['MEDIA-flow', 'MEDIA-flow']}, 'without repeats'),
                             ({**auto, 'case_id': 'C3', 'reference_media_ids': ['MEDIA-flow']}, 'does not show case C3'),
                             (self.visual(case_id='C3'), 'does not show its case')):
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                reference_media.plan_gate(self.s, m, plan(bad))
        with carrying() as gaps:
            reference_media.freeze(self.s, {**m, 'plan': plan(auto)})
        self.assertEqual(sorted(g.split(':')[0] for g in gaps), ['the user showed C1 in MEDIA-flow', 'the user showed C1 in MEDIA-login'])  # MEDIA-third shows no case of this leaf
        cited = plan({**auto, 'reference_media_ids': ['MEDIA-flow']}, self.visual())
        with carrying() as gaps:
            reference_media.freeze(self.s, {**m, 'plan': cited})
        self.assertEqual(gaps, [])
        with carrying() as gaps:  # a declared device gap is reported already: nothing more is owed for the case
            reference_media.freeze(self.s, {**m, 'plan': plan(auto, device_gaps=[{'case_id': 'C1', 'reason': 'no device', 'evidence_refs': []}])})
        self.assertEqual(gaps, [])
        self.s['modules'] = {'M001': {**m, 'plan': cited}, 'M002': {'module_id': 'M002', 'case_ids': ['C2'], 'plan': plan(auto)}}
        self.assertEqual([(r['media_id'], r['modules'], r['cited_by'], r['status']) for r in reference_media.report(self.s)],
                         [('MEDIA-login', ['M001'], ['M001:PV'], 'cited'), ('MEDIA-flow', ['M001', 'M002'], ['M001:P1'], 'cited'),
                          ('MEDIA-third', [], [], 'uncited')])

    def manifest(self, shot):
        view = self.base / 'view.xml'
        view.write_text('<hierarchy><node class="android.widget.TextView" resource-id="app:id/title" text="Login" bounds="[0,0][100,40]" enabled="true" /></hierarchy>')
        meta = self.base / 'meta.json'
        meta.write_text(json.dumps({'screenshot': Path(shot['path']).name, 'page_name': 'Login', 'foreground': 'app/.Login', 'view_signature': 'sig'}))
        coverage = {'requested': 'viewport', 'achieved': 'viewport', 'capture_count': 1, 'termination': 'viewport'}
        snapshot = {'screenshot': shot['path'], 'view_tree': str(view), 'meta': str(meta), 'view_signature': 'sig',
                    'device_backend': {'name': 'user', 'version': 'reference', 'device': 'user-media'}, 'coverage': coverage,
                    'captures': [{'index': 0, 'screenshot': shot['path'], 'view_tree': str(view), 'view_signature': 'sig'}]}
        record = {'mode': 'targeted', 'phase': 'android-reference', 'platform': 'android', 'page_id': 'login', 'state_id': 'base',
                  'observed_variant': 'base', 'round': None, 'status': 'COMPLETE', 'coverage': coverage, 'snapshot': snapshot}
        return self.ref(f"manifest-{shot['sha256'][:6]}.json", {'schema_version': 2, 'capture_id': 'user-reference', 'targets': [record]})

    def test_a_user_reference_is_frozen_evidence_and_its_reference_record_is_exactly_its_screenshots(self):
        module = {'plan': {'dimension_analysis_ref': self.ref('analysis.json', self.analysis(self.evidence()))}}
        self.assertEqual(visual_evidence.frozen_evidence(module, self.visual())['visual_mode'], 'user-reference')
        self.assertIsNone(visual_evidence.frozen_evidence(module, self.visual(baseline_ref=self.other)))
        self.assertEqual(visual_evidence.match_source(self.manifest(self.shot), self.evidence(), 'login:base:viewport')['status'], 'COMPLETE')
        with self.assertRaisesRegex(Rejected, 'exactly the user reference screenshots'):
            visual_evidence.match_source(self.manifest(self.other), self.evidence(), 'login:base:viewport')


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        shot, clip = media_row(base), media_row(base, 'flow.mp4')
        original = pc.update

        def with_media(root, request, actor, initialize=False):
            if initialize:
                request = {**request, 'patch': {**request['patch'], 'reference_media': [shot, clip]}}
            return original(root, request, actor, initialize)
        with mock.patch.object(pc, 'update', with_media):
            self.t = test_source_changes.SourceChangeTests(); self.t.setUp()
        self.addCleanup(self.t.doCleanups)
        self.f = self.t.f

    def test_the_leaf_reads_what_the_user_showed_and_cites_it_in_its_skeleton_plan_and_report(self):
        f = self.f; s = f.state()
        assigned = decomposition.assigned_module(s, s['modules']['M001'])
        self.assertEqual([r['media_id'] for r in assigned['reference_media']], ['MEDIA-login', 'MEDIA-flow'])
        files = spec_skeleton.write(f.root, 'M001', f.root / 'staging/spec-designer/media-skeleton')['files']
        upstream = json.loads(check_ref(files['upstream-test-plan.json']).read_text())
        visual = [p for p in upstream['paths'] if p['kind'] == 'visual']
        self.assertEqual([(p['case_id'], p['baseline_ref']['sha256'], p['reference_media_ids']) for p in visual],
                         [('C1', assigned['reference_media'][0]['ref']['sha256'], ['MEDIA-login'])])
        flow = next(p for p in upstream['paths'] if p['kind'] == 'automation' and p['case_id'] == 'C1')
        self.assertEqual(flow['reference_media_ids'], ['MEDIA-flow'])
        self.assertIn('MEDIA-login', check_ref(files['design.md']).read_text())
        from test_iterative_spec import direct_plan
        plan = self.t.plan('M001')
        plan['paths'][0]['reference_media_ids'] = ['MEDIA-nope']
        bad = copy.deepcopy(plan); direct_plan(f, bad)
        with self.assertRaisesRegex(Rejected, 'name the run reference media'):
            f.call('plan', {'plan_ref': f.ref('plan-bad.json', bad)}, role='spec-designer', module='M001')
        plan['paths'][0]['reference_media_ids'] = ['MEDIA-flow']
        direct_plan(f, plan)
        f.call('plan', {'plan_ref': f.ref('plan-M001.json', plan)}, role='spec-designer', module='M001')
        s = f.state()
        holders = sorted(mid for mid, m in s['modules'].items() if 'C1' in m['case_ids'])
        report = migration_report.build(f.root, s, s['last_sequence'])
        self.assertEqual([(r['media_id'], r['modules'], r['cited_by'], r['status']) for r in report['reference_media']],
                         [('MEDIA-login', holders, [], 'uncited'), ('MEDIA-flow', holders, ['M001:M001-P'], 'cited')])
        self.assertIn('## 用户参考媒体', migration_report.render(report))


class ExpectationTests(unittest.TestCase):
    """What the user says the target should look like replaces the legacy baseline of the screens it covers."""
    def setUp(self):
        self.g = g = GateTests(); g.setUp(); self.addCleanup(g.doCleanups)
        self.design = g.ref('design.png', 'what the target login should look like')
        rows = [{'media_id': 'MEDIA-login', 'kind': 'screenshot', 'role': 'legacy-baseline', 'screen': 'login', 'case_ids': ['C1'], 'ref': g.shot},
                {'media_id': 'MEDIA-design', 'kind': 'screenshot', 'role': 'target-expectation', 'screen': 'login', 'case_ids': ['C1'], 'ref': self.design}]
        g.s['project_context_ref'] = g.ref('snapshot-expectation.json', {'source_refs': {'reference_media': rows}})

    def test_the_expectation_is_the_baseline_shapes_the_design_and_is_disclosed(self):
        g = self.g
        self.assertEqual(reference_media.configured([{'media_id': 'D', 'kind': 'screenshot', 'path': self.design['path'], 'role': 'target-expectation', 'case_ids': ['C1']}])[0]['role'],
                         'target-expectation')
        expected = g.evidence(legacy_executable=True, baseline_refs=[self.design])
        g.baseline_gate(expected, [g.visual(baseline_ref=self.design)])  # previewable or not, the screen is aligned to the expectation
        with self.assertRaisesRegex(Rejected, 'gave a target expectation for this screen'):
            g.baseline_gate(g.evidence(legacy_executable=True, visual_mode='runtime', baseline_refs=[g.other]), [g.visual(baseline_ref=g.other)])
        with self.assertRaisesRegex(Rejected, 'target expectation screenshots of the cases'):
            g.baseline_gate(g.evidence(), [g.visual()])  # the legacy screenshot is input now, not the baseline
        analysis = g.ref('analysis-expected.json', g.analysis(expected))

        def plan(*paths, design='the login follows MEDIA-design', **over):
            return {'dimension_analysis_ref': analysis, 'paths': list(paths), 'definitions': [{**g.ref(f'design-{len(design)}.md', design), 'kind': 'design'}], **over}
        m = {'module_id': 'M001', 'case_ids': ['C1']}
        with self.assertRaisesRegex(Rejected, 'MEDIA-design shapes the design'), carrying():
            reference_media.freeze(g.s, {**m, 'plan': plan(g.visual(baseline_ref=self.design), design='no mention of it')})
        with carrying() as gaps:
            reference_media.freeze(g.s, {**m, 'plan': plan(g.visual(baseline_ref=self.design))})
        self.assertEqual(gaps, [])  # the legacy screenshot of a replaced screen is not owed a citation
        with carrying() as gaps:
            reference_media.freeze(g.s, {**m, 'plan': plan({'path_id': 'P1', 'kind': 'automation', 'case_id': 'C1'})})
        self.assertEqual([gap.split(':')[0] for gap in gaps], ['the user showed C1 in MEDIA-design'])
        g.s['modules'] = {'M001': {**m, 'plan': plan(g.visual(baseline_ref=self.design))}}
        self.assertEqual([(r['media_id'], r['status'], r['overrides']) for r in reference_media.report(g.s)],
                         [('MEDIA-login', 'uncited', []), ('MEDIA-design', 'cited', ['MEDIA-login'])])
        disclosure, = reference_media.disclosures(g.s)
        self.assertEqual((disclosure['module_id'], disclosure['kind'], disclosure['case_ids'], disclosure['evidence_refs']), ('M001', 'target-expectation', ['C1'], [self.design]))
        self.assertIn('MEDIA-design', disclosure['reason']); self.assertIn('MEDIA-login', disclosure['reason'])


if __name__ == '__main__':
    unittest.main()
