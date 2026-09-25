"""Four-dimension planning gates, inheritance and frozen evidence in real Ledger transitions."""
import copy
import json
from pathlib import Path
import unittest

import test_ledger
import test_decomposition
from contracts import Rejected, check_ref, digest, file_ref, baseline, validate_plan, verify_plan
import dimensions


class DimensionTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_decomposition.DecompositionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)

    def analysis(self, mid='M010', kinds=('Logic',), parent_ref=None, semantic=False):
        f = self.f
        proof = f.ref('dimension-source.md', 'Versioned source/target review: entry -> handler -> repository -> consumer')
        rows = []
        for kind in dimensions.ORDER:
            item = {'item_id': mid + '-' + kind, 'behavior': 'observable feature', 'requirement_ids': ['R1'],
                    'case_ids': ['C1'], 'source_locator': 'legacy/file#entry', 'target_strategy': 'new',
                    'target_binding': 'target/file#entry', 'acceptance': 'same observable result', 'evidence_refs': [proof],
                    'parent_item_ids': ['M010-' + kind] if parent_ref else []}
            if kind == 'Resource':
                item.update(source_resource='legacy/icon.svg', target_resource=str(f.target / 'm1/icon.svg'),
                            consumer=str(f.target / 'm1/app.py'), conversion='exact-copy', qualifiers='default only; inspected')
            if semantic and kind == 'Logic':
                # strategy is 'new', so the model is authored from the target (never legacy origin).
                item['semantic_model'] = {'kind': 'logic-statechart',
                    'model_ref': f.ref(mid + '-statechart.json', {'id': mid, 'initial': 'idle',
                        'states': {'idle': {'on': {'GO': {'target': 'run', 'cond': {'==': [1, 1]}}}}, 'run': {}}}),
                    'source': {'origin': 'authored', 'evidence_refs': []},
                    'implementation_location': {'target_path': str(f.target / 'm1/Logic.kt'), 'symbol': 'reducer'}}
            rows.append({'dimension': kind, 'status': 'applicable' if kind in kinds else 'not-applicable',
                         'reason': 'source-backed scope analysis', 'evidence_refs': [proof],
                         'items': [item] if kind in kinds else []})
        return {'schema_version': 1, 'module_id': mid, 'parent_ref': parent_ref,
                'scope': {'in': ['feature' if mid == 'M010' else 'subfunction-' + mid],
                          'out': ['Orders'], 'requirement_ids': ['R1']},
                'source_reviews': {k: {'conclusion': 'reviewed source and candidate semantics', 'evidence_refs': [proof]}
                                   for k in dimensions.SOURCES}, 'dimensions': rows, 'unresolved': []}

    def root(self, kinds=('Logic',)):
        f = self.f
        old = f.state(); f.root = f.base / 'dimension-run'
        payload = {k: old[k] for k in ('target_root', 'legacy_root', 'global_spec', 'new_architecture',
                                      'case_ids', 'requirement_ids', 'global_paths')}
        payload.update(context_readiness_required=False, split_testing_required=False)
        f.call('init', payload, role='host')  # Test the default, not an explicit opt-in.
        self.assertTrue(f.state()['dimension_slicing_required'])
        module = {'module_id': 'M010', 'case_ids': ['C1'], 'write_paths': [str(f.target)],
                  'scope': {'in': ['feature'], 'out': ['Orders'], 'requirement_ids': ['R1']},
                  'context_refs': [f.ref('context.md', 'full allocated context')], 'decomposition_required': True}
        with self.assertRaisesRegex(Rejected, 'evidence path'):
            f.call('register', module, role='global-orchestrator', module=None)
        module['dimension_analysis_ref'] = f.ref('root-dimensions.json', self.analysis(kinds=kinds))
        f.call('register', module, role='global-orchestrator', module=None)
        self.root_ref = module['dimension_analysis_ref']
        return module

    def proposal(self, kinds=('Logic',), ids=('M001',), semantic=False):
        f = self.f
        p = f.proposal(ids=ids)
        p['dimension_partition_review_ref'] = f.ref('partition-review.md', 'Subfunctions partition source behaviors; shared providers have one writer')
        for child in p['children']:
            child['dimension_analysis_ref'] = f.ref(child['module_id'] + '-dimensions.json',
                self.analysis(child['module_id'], kinds, self.root_ref, semantic))
        return p

    def leaf_plan(self):
        f = self.f
        p = f.plan()
        p.update(planning_context=f.state()['planning_context'], assigned_module=f.state()['module_inputs']['M001'],
                 dimension_analysis_ref=f.state()['modules']['M001']['dimension_analysis_ref'])
        _, items = dimensions.load(p['dimension_analysis_ref'], 'M001')
        p['dimension_trace'] = [{'item_id': iid, 'task_ids': ['T1'], 'path_ids': ['P1'],
                               'assertions': [{'path_id': 'P1', 'assertion_id': 'A1'}]} for iid in items]
        for task in p['tasks']:
            task['scope'] = {'in': ['implement assigned subfunction'], 'out': ['Orders'],
                             'write_paths': [str(f.target / 'm1')]}
            task['dimension_analysis'] = {'scope_sha256': digest(task['scope']), 'parent_ref': p['dimension_analysis_ref'],
                'unresolved': [], 'dimensions': [
                    {'dimension': kind, 'status': 'applicable' if any(i['dimension'] == kind for i in items.values()) else 'not-applicable',
                     'reason': 'reviewed this task scope', 'item_ids': [iid for iid, item in items.items() if item['dimension'] == kind],
                     'implementation': 'Preserve source behavior, bind target consumer and verify A1 within task scope',
                     'evidence_refs': [f.ref('task-analysis-source.md', 'Task-specific implementation and existing target seam reviewed')]}
                    for kind in dimensions.ORDER]}
        for d in p['definitions']:
            if d['kind'] in ('design', 'spec', 'tasks'):
                path = check_ref(d)
                path.write_text(path.read_text() + '\nDimension coverage: ' + ', '.join(items) + '\n')
                d.update(file_ref(path))
        return p

    def test_full_register_decompose_plan_freeze_implementation_projection(self):
        f = self.f
        self.root(kinds=tuple(dimensions.ORDER)); f.split(self.proposal(tuple(dimensions.ORDER))); f.global_plan()
        p = self.leaf_plan()
        f.call('plan', {'plan_ref': f.ref('plan-dimensions.json', p)}, role='spec-designer')
        f.call('decision', {'decision_id': 'D', 'decision': 'approved', 'module_id': 'M001', 'subject_sha256': digest(p),
                           'human_source_ref': f.ref('approve.md', 'User approved concrete plan')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'D'})
        view = f.root / 'openspec/changes/demo-m001/dimensions.md'
        self.assertIn('M001-Resource', view.read_text())
        self.assertEqual(f.state()['module_inputs']['M001']['dimension_analysis_ref'], p['dimension_analysis_ref'])
        self.assertIn('M010', f.state()['planning_context']['dimension_allocations'])
        submit = f.call('assign', {'role': 'implementer', 'assignment_id': 'I1', 'instance_id': 'coder'})
        # Exercise implementation evidence through the same contract called by submit.
        with self.assertRaisesRegex(Rejected, 'item_id'):
            dimensions.implementation(p, {})
        resource = f.ref('target/m1/icon.svg', '<svg/>')
        consumer = f.ref('target/m1/app.py', 'ICON = "icon.svg"')
        result = {'dimension_evidence': [{'item_id': t['item_id'], 'task_ids': ['T1'], 'summary': 'actual implementation binding',
                    'evidence_refs': [consumer], **({'target_resource_ref': resource, 'consumer_ref': consumer}
                    if t['item_id'].endswith('Resource') else {})} for t in p['dimension_trace']]}
        dimensions.implementation(p, result)
        saved = copy.deepcopy(result)
        del result['dimension_evidence'][-1]['consumer_ref']
        with self.assertRaises(Rejected):
            dimensions.implementation(p, result)
        self.assertTrue(submit)
        a = f.state()['modules']['M001']['assignments']['I1']
        source = f.ref('target/m1/code.py', 'value = 2\n')
        refs = [source, resource, consumer]
        result = {**saved, 'schema_version': 1, 'kind': 'implementation', 'run_id': 'demo', 'module_id': 'M001',
                  'assignment_id': 'I1', 'actor_instance_id': 'coder', 'freeze_id': a['freeze_id'],
                  'code_files': refs, 'code_baseline': baseline(refs),
                  'task_trace': [{'task_id': 'T1', 'files': [r['path'] for r in refs]}],
                  'production_binding_evidence': consumer}
        f.call('submit', {'assignment_id': 'I1', 'fencing_token': a['fencing_token'],
                         'result_ref': f.ref('implementation.json', result)}, role='implementer', instance='coder')
        f.call('accept', {'assignment_id': 'I1'})
        f.complete_leaf('M001'); f.summarize()
        self.assertEqual(f.state()['modules']['M001']['quality'], 'green-passed')
        self.assertEqual(f.state()['module_groups']['M010']['phase'], 'completed')

    def test_semantic_model_frozen_and_projected(self):
        f = self.f
        self.root(kinds=tuple(dimensions.ORDER)); f.split(self.proposal(tuple(dimensions.ORDER), semantic=True)); f.global_plan()
        p = self.leaf_plan()
        f.call('plan', {'plan_ref': f.ref('plan-dimensions.json', p)}, role='spec-designer')
        f.call('decision', {'decision_id': 'D', 'decision': 'approved', 'module_id': 'M001', 'subject_sha256': digest(p),
                           'human_source_ref': f.ref('approve.md', 'User approved concrete plan')}, role='host', module=None)
        f.call('freeze', {'decision_id': 'D'})
        view = f.root / 'openspec/changes/demo-m001/semantics.md'
        self.assertTrue(view.exists())
        text = view.read_text()
        self.assertIn('logic-statechart', text)
        self.assertIn('M001-Logic', text)
        self.assertIn('implementation_location', text)
        # Global semantic context is aggregated across modules with per-module coverage.
        index = json.loads((f.root / 'ledger/semantic-index.json').read_text())
        self.assertTrue(any(r['module_id'] == 'M001' and r['kind'] == 'logic-statechart' for r in index['models']))
        self.assertIn('M001-Logic', index['coverage']['M001']['with_model'])

    def test_semantic_model_kind_must_match_dimension(self):
        # A UI-kind model on a Logic item is rejected at plan load (structural gate).
        self.root(kinds=('Logic',))
        analysis = self.analysis('M001', ('Logic',), self.root_ref, semantic=True)
        for row in analysis['dimensions']:
            if row['dimension'] == 'Logic':
                row['items'][0]['semantic_model']['kind'] = 'ui-component-spec'
        with self.assertRaisesRegex(Rejected, 'kind does not match'):
            dimensions.load(self.f.ref('bad-semantics.json', analysis), 'M001')

    def test_reused_resource_consumer_change_invalidates_accepted_evidence(self):
        f = self.f
        resource = f.ref('reused/icon.svg', '<svg/>')
        consumer = f.ref('reused/consumer.py', 'icon = "icon.svg"')
        code = f.ref('target/module.py', 'value = 2')
        m = {'code_files': [code], 'dimension_evidence': [{'evidence_refs': [resource],
             'target_resource_ref': resource, 'consumer_ref': consumer}]}
        dimensions.current(m)
        Path(consumer['path']).write_text('icon = "other.svg"')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            dimensions.current(m)
        m['code_files'] = []  # Existing invalidate -> implement route remains usable.
        dimensions.current(m)

    def test_na_requires_evidence_and_unknown_or_wrong_order_rejected(self):
        f = self.f
        data = self.analysis()
        dimensions.load(f.ref('valid.json', data), 'M010')  # pure Logic is supported
        for change, message in (
            (lambda d: d['dimensions'].reverse(), 'order'),
            (lambda d: d['dimensions'][0].update(evidence_refs=[]), 'evidence'),
            (lambda d: d['dimensions'][0].update(status='unknown'), 'unresolved'),
            (lambda d: d.update(unresolved=['ambiguous dependency']), 'uncertainty'),
            (lambda d: d['source_reviews'].pop('target'), 'legacy/architecture/reuse/target'),
        ):
            bad = copy.deepcopy(data); change(bad)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                dimensions.load(f.ref('bad.json', bad), 'M010')

    def test_parent_applicable_cannot_disappear_or_cross_dimension(self):
        f = self.f
        self.root(('Logic', 'Resource'))
        p = self.proposal(('Logic',))
        with self.assertRaisesRegex(Rejected, 'omit parent'):
            f.call('decompose', {'plan_ref': f.ref('bad-split.json', p)}, module='M010')
        p = self.proposal(('Logic', 'Resource'))
        data = self.analysis('M001', ('Logic', 'Resource'), self.root_ref)
        data['dimensions'][1]['items'][0]['parent_item_ids'] = ['M010-Resource']
        p['children'][0]['dimension_analysis_ref'] = f.ref('wrong-dimension.json', data)
        with self.assertRaisesRegex(Rejected, 'dimension changed'):
            f.call('decompose', {'plan_ref': f.ref('wrong-split.json', p)}, module='M010')

    def test_partition_review_and_unique_child_items_required(self):
        f = self.f; self.root()
        p = self.proposal(ids=('M001','M002'))
        del p['dimension_partition_review_ref']
        with self.assertRaises(Rejected):
            f.call('decompose', {'plan_ref': f.ref('missing-review.json', p)}, module='M010')
        p = self.proposal(ids=('M001','M002'))
        d = self.analysis('M002', parent_ref=self.root_ref)
        d['dimensions'][1]['items'][0]['item_id'] = 'M001-Logic'
        p['children'][1]['dimension_analysis_ref'] = f.ref('duplicate-item.json', d)
        with self.assertRaisesRegex(Rejected, 'ownership duplicated'):
            f.call('decompose', {'plan_ref': f.ref('duplicate-split.json', p)}, module='M010')

    def test_leaf_cannot_skip_trace_and_build_cannot_replace_behavior(self):
        f = self.f; self.root(); f.split(self.proposal()); f.global_plan()
        p = self.leaf_plan(); m = f.state()['modules']['M001']
        validate_plan(p, m)
        for change, message in (
            (lambda p: p.pop('dimension_analysis_ref'), 'allocated dimension'),
            (lambda p: p.update(dimension_trace=[]), 'item_id'),
            (lambda p: p['dimension_trace'][0].update(task_ids=['OTHER']), 'unknown task/path'),
            (lambda p: p['dimension_trace'][0]['assertions'][0].update(assertion_id='OTHER'), 'unknown dimension assertion'),
            (lambda p: p['paths'][0].update(kind='build'), 'build alone'),
        ):
            bad=copy.deepcopy(p); change(bad)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected,message):
                validate_plan(bad,m)

    def test_task_scope_and_four_dimensions_gate_freeze(self):
        f = self.f; self.root(); f.split(self.proposal()); f.global_plan()
        p = self.leaf_plan(); m = f.state()['modules']['M001']
        validate_plan(p, m)  # UI/Adhesive/Resource can be N/A for a Logic-only task.
        for change, message in (
            (lambda p: p['tasks'][0].pop('scope'), 'task business scope'),
            (lambda p: p['tasks'][0]['scope']['in'].append('unreviewed work'), 'bind current task scope'),
            (lambda p: p['tasks'][0]['scope'].update(write_paths=[str(f.target / 'other')]), 'outside assigned module'),
            (lambda p: p['tasks'][0]['dimension_analysis']['dimensions'].pop(), 'order incomplete'),
            (lambda p: p['tasks'][0]['dimension_analysis']['dimensions'][1].update(status='not-applicable'), 'N/A cannot'),
            (lambda p: p['tasks'][0]['dimension_analysis']['dimensions'][1].pop('implementation'), 'implementation guidance'),
            (lambda p: p['tasks'][0]['dimension_analysis']['dimensions'][0].update(evidence_refs=[]), 'task dimension evidence'),
        ):
            bad = copy.deepcopy(p); change(bad)
            with self.subTest(message=message), self.assertRaisesRegex(Rejected, message):
                validate_plan(bad, m)

    def test_module_analysis_bound_to_scope_and_task_evidence_stays_current(self):
        f = self.f; module = self.root()
        module['scope']['in'].append('expanded feature')
        with self.assertRaisesRegex(Rejected, 'already allocated module scope'):
            dimensions.allocation(f.state(), module)
        f.split(self.proposal()); f.global_plan()
        p = self.leaf_plan(); verify_plan(p)
        (f.base / 'task-analysis-source.md').write_text('changed task context')
        with self.assertRaisesRegex(Rejected, 'hash mismatch'):
            verify_plan(p)

    def test_implementation_cannot_escape_task_scope_inside_module(self):
        f = self.f; self.root(); f.split(self.proposal()); f.global_plan()
        p = self.leaf_plan()
        p['tasks'][0]['scope']['write_paths'] = [str(f.target / 'm1/parser.py')]
        result = {'dimension_evidence': [{'item_id': 'M001-Logic', 'task_ids': ['T1'],
                    'summary': 'implementation', 'evidence_refs': [f.ref('impl.md', 'implementation reviewed')]}],
                  'task_trace': [{'task_id': 'T1', 'files': [str(f.target / 'm1/unrelated.py')]}]}
        with self.assertRaisesRegex(Rejected, 'outside planned task scope'):
            dimensions.implementation(p, result)

    def test_changed_nested_evidence_invalidates_frozen_plan(self):
        f=self.f; self.root(); f.split(self.proposal()); f.global_plan()
        p=self.leaf_plan(); verify_plan(p)
        Path(f.base / 'dimension-source.md').write_text('changed source baseline')
        with self.assertRaisesRegex(Rejected,'hash mismatch'):
            verify_plan(p)


if __name__ == '__main__':
    unittest.main()
