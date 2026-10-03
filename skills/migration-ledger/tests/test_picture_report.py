"""The GO report discloses every picture the target does not copy, and whether the screen measurement backs it."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import migration_report
import test_ledger

DEVIATION = {'alternative': 'draw the arrow as a shape', 'kind': 'redraw', 'reason': 'the vector uses a gradient'}


class PictureReportTests(unittest.TestCase):
    def setUp(self):
        self.f = test_ledger.FlowTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def picture(self, item_id, **over):
        return {'item_id': item_id, 'source_resource': '@drawable/' + item_id, 'resource_kind': 'vector',
                'resource_strategy': 'manual_exact', **over}

    def analysis(self, *items):
        return {'dimensions': [{'dimension': 'UI', 'status': 'not-applicable', 'reason': 'out of scope'},
                               {'dimension': 'Resource', 'status': 'applicable', 'items': list(items)}]}

    def disclose(self, *items, paths=(), rows=()):
        ref = self.f.ref('pictures.json', self.analysis(*items))
        state = {'modules': {'M001': {'plan': {'dimension_analysis_ref': ref, 'paths': list(paths)}}}}
        return migration_report.fidelity(state, list(rows), lambda r: Path(r['path']))

    def row(self, path_id='PV', **over):
        return {'module_id': 'M001', 'path_id': path_id, 'kind': 'visual', 'coverage': 'p:s:viewport',
                'quality': 'green-passed', 'executed': True, 'stale': False, 'evidence_refs': [], **over}

    def statuses(self, pictures):
        return {v['item_id']: v['status'] for v in pictures['items']}

    def test_copies_are_counted_and_everything_else_is_listed(self):
        _, limitations, pictures = self.disclose(
            self.picture('copy', resource_strategy='exact_vector_xml'),
            self.picture('hand_drawn', image_check='hand-drawn'),
            self.picture('gradient', deviation=DEVIATION),
            self.picture('gone', resource_strategy='blocked', blocked_reason='no converter'),
            self.picture('loader', resource_kind='remote-image', source_resource=None, source_signal='src:remote-image:ab12'),
            self.picture('spinner', resource_kind='animated-vector', resource_strategy='blocked', blocked_reason='needs an animator port'),
            self.picture('ring', resource_kind='code-drawn', source_resource=None, source_signal='src:code-drawn:cd34'),
            {'item_id': 'title', 'source_resource': '@string/title', 'resource_kind': 'string', 'resource_strategy': 'value_xml_exact'},
            paths=[{'path_id': 'PV', 'kind': 'visual', 'image_check_ids': ['hand-drawn']}], rows=[self.row()])
        self.assertEqual(self.statuses(pictures), {'hand_drawn': 'verified', 'gradient': 'approved-deviation', 'gone': 'blocked',
                                                   'loader': 'reviewed', 'spinner': 'blocked', 'ring': 'reviewed'})
        self.assertEqual(pictures['counts'], {'exact': 1, 'verified': 1, 'approved-deviation': 1, 'blocked': 2, 'reviewed': 2})
        self.assertEqual({v['item_id'] for v in limitations if v['kind'] == 'picture-replacement'}, {'gradient', 'gone', 'spinner'})
        reasons = {v['item_id']: v['reason'] for v in limitations}
        self.assertIn('redraw', reasons['gradient']); self.assertIn('the vector uses a gradient', reasons['gradient'])
        self.assertIn('no converter', reasons['gone'])

    def test_a_replacement_is_verified_only_by_a_current_green_executed_check(self):
        item = self.picture('hand_drawn', image_check='hand-drawn')
        carried = [{'path_id': 'PV', 'kind': 'visual', 'image_check_ids': ['hand-drawn']}]
        for over, reason in (({'quality': 'red-bug'}, '未在当前基线通过'), ({'stale': True}, '未在当前基线通过'), ({'executed': False}, '未在当前基线通过')):
            _, limitations, pictures = self.disclose(item, paths=carried, rows=[self.row(**over)])
            self.assertEqual(self.statuses(pictures), {'hand_drawn': 'not-verified'}, over)
            self.assertIn(reason, limitations[-1]['reason'])
        _, limitations, pictures = self.disclose(item, paths=carried)
        self.assertEqual(self.statuses(pictures), {'hand_drawn': 'not-verified'})
        _, limitations, pictures = self.disclose(item, paths=[{'path_id': 'PV', 'kind': 'unit', 'image_check_ids': ['hand-drawn']}], rows=[self.row()])
        self.assertEqual(self.statuses(pictures), {'hand_drawn': 'not-verified'})
        _, limitations, pictures = self.disclose(self.picture('hand_drawn'))
        self.assertEqual(self.statuses(pictures), {'hand_drawn': 'not-verified'})
        self.assertIn('没有图像检查', limitations[-1]['reason'])

    def test_a_check_carried_by_several_paths_needs_all_of_them_current(self):
        carried = [{'path_id': 'PA', 'kind': 'visual', 'image_check_ids': ['shared']}, {'path_id': 'PB', 'kind': 'visual', 'image_check_ids': ['shared']}]
        item = self.picture('shared_icon', image_check='shared')
        both = [self.row('PA'), self.row('PB')]
        self.assertEqual(self.statuses(self.disclose(item, paths=carried, rows=both)[2]), {'shared_icon': 'verified'})
        both[1]['stale'] = True
        self.assertEqual(self.statuses(self.disclose(item, paths=carried, rows=both)[2]), {'shared_icon': 'not-verified'})

    def test_report_and_markdown_carry_the_disclosure(self):
        f = self.f; f.test_green_flow_and_independent_global_audit()
        state = f.state()
        state['modules']['M001']['plan']['dimension_analysis_ref'] = f.ref('disclosure.json', self.analysis(
            self.picture('gradient', deviation=DEVIATION), self.picture('copy', resource_strategy='exact_vector_xml')))
        report = migration_report.build(f.root, state, state['last_sequence'])
        self.assertEqual(report['picture_fidelity']['counts'], {'approved-deviation': 1, 'exact': 1})
        self.assertEqual(report['report_stage'], 'completed')  # a disclosure never changes the acceptance
        markdown = migration_report.render(report)
        self.assertIn('| M001 / gradient | @drawable/gradient | vector / manual_exact | approved-deviation |', markdown)
        self.assertNotIn('@drawable/copy', markdown)
        self.assertIn('图片统计', markdown)
        del report['picture_fidelity']
        self.assertNotIn('图片统计', migration_report.render(report))


if __name__ == '__main__':
    unittest.main()
