"""The Ledger writes the executing roles' report skeletons; a report that still holds a mark is refused."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import audit_code_review
import context_readiness as cr
import report_skeleton
import spec_closure
import test_audit_closure
import test_spec_closure
from contracts import SKELETON_MARK, Rejected, check_ref, file_ref


def filled(text):
    while SKELETON_MARK in text:
        start = text.index(SKELETON_MARK); end = text.index(']]', start) + 2
        text = text[:start] + 'written' + text[end:]
    return text


class ReportSkeletonTests(unittest.TestCase):
    def test_the_test_runner_preflight_and_static_review_come_as_skeletons(self):
        t = test_spec_closure.SpecClosureTests(); t.setUp(); self.addCleanup(t.doCleanups)
        t.built(); f = t.f
        out = f.root / 'staging/test-runner/STATIC1'
        result = report_skeleton.write(f.root, out, 'M001', 'STATIC1')
        files = result['files']
        self.assertEqual(set(files), {'preflight-building.json', 'static-review.json'}); self.assertGreater(result['unfilled'], 10)
        pre = json.loads(check_ref(files['preflight-building.json']).read_text())
        s = f.state(); plan = s['modules']['M001']['plan']
        self.assertEqual(pre['subject_sha256'], cr.subject(s, 'M001', 'building'))
        self.assertEqual(set(pre['execution']['commands']), {'S1'})  # the review's own dispatch: the build already passed
        self.assertIn(SKELETON_MARK, pre['execution']['commands']['S1']['argv'][0])
        self.assertEqual(pre['checks']['frozen-spec']['status'], 'ready'); self.assertIn(SKELETON_MARK, pre['checks']['build-environment']['status'])
        with self.assertRaisesRegex(Rejected, 'unfilled skeleton field left in preflight-building.json'):
            f.raw('context-submit', {'report_ref': files['preflight-building.json']}, role='test-runner', instance='test-runner')
        proof = f.ref('probe.md', 'JDK and SDK probed on this host')
        for name in ('build-environment', 'permissions-tools'):
            pre['checks'][name] = {'status': 'ready', 'summary': 'probed on this host', 'evidence_refs': [proof]}
        pre['execution']['commands']['S1'] = {'argv': t.static_argv(), 'cwd': str(f.target)}
        pre['execution'].update(argv=t.static_argv(), cwd=str(f.target))  # the review is this dispatch's only command
        pre['execution']['environment_ref'] = f.ref('build-env.md', 'Python build fixture'); pre['verdict'] = 'ready'
        ref = f.ref('preflight-filled.json', pre)
        f.raw('context-submit', {'report_ref': ref}, role='test-runner', instance='test-runner')
        self.assertEqual(f.state()['modules']['M001']['context_receipts']['building:test-runner']['report_ref'], ref)
        review = json.loads(check_ref(files['static-review.json']).read_text())
        self.assertEqual([row['requirement_id'] for row in review['scenarios']], ['R1'])
        self.assertEqual(set(review['anti_patterns']), set(spec_closure.ANTI_PATTERNS))
        self.assertEqual((review['path_id'], review['freeze_id']), ('S1', s['modules']['M001']['freeze_id']))
        query = {'kind': 'static', 'expected_assertions': plan['paths'][-1]['expected_assertions'], 'scenario_requirement_ids': ['R1'],
                 **{k: review[k] for k in ('run_id', 'module_id', 'path_id', 'freeze_id', 'code_baseline')}}
        with self.assertRaisesRegex(Rejected, 'unfilled skeleton field left in the static review'):
            spec_closure.report(query, f.ref('review-unfilled.json', review), str(f.target))
        done = t.review()  # the reviewer's content in the skeleton's rows
        review['scenarios'] = [{**review['scenarios'][0], **done['scenarios'][0]}]
        review['anti_patterns'] = done['anti_patterns']; review['independence'] = 'wrote none of the code'
        self.assertEqual(t.run_static(review)['quality'], 'green-passed')

    def test_the_auditors_inventory_and_review_come_as_skeletons(self):
        f = test_audit_closure.ClosureTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.prepare(); f.implement('M001', 'I1'); f.verify_module('M001', 'T1'); f.complete('M001')
        step = f.state()['global_next_step']
        self.assertEqual(step['operation'], 'audit-code-review'); self.assertIn('--global', step['report_skeleton'])
        f.call('issue', {'issue_id': 'DEBT-1', 'kind': 'debt', 'summary': 'temporary adapter duplicates the shared mapper', 'applies_to': ['M001']},
               role='implementer', module=None)
        with self.assertRaisesRegex(Rejected, 'cannot block'):
            f.call('issue', {'issue_id': 'DEBT-2', 'kind': 'debt', 'summary': 'x', 'applies_to': ['M001'], 'blocks': True}, role='implementer', module=None)
        out = f.root / 'staging/auditor/review'
        result = report_skeleton.write(f.root, out)
        files = result['files']
        self.assertEqual(set(files), {'audit-change-inventory.md', 'audit-code-review.json'})
        text = check_ref(files['audit-change-inventory.md']).read_text()
        self.assertIn('temporary adapter duplicates the shared mapper', text); self.assertIn('issue DEBT-1', text)
        s = f.state(); code = s['modules']['M001']['code_files'][0]
        self.assertIn('| CHG-001 | M001 / T1 |', text); self.assertIn(code['path'], text); self.assertIn('| M001 / C1 | P1 /', text)
        review = json.loads(check_ref(files['audit-code-review.json']).read_text())
        self.assertEqual(review['snapshot'], audit_code_review.snapshot(s))
        self.assertEqual(review['change_inventory_ref'], files['audit-change-inventory.md'])
        self.assertEqual([m['module_id'] for m in review['modules']], ['M001']); self.assertEqual(review['debts'], ['DEBT-1'])
        self.assertEqual(review['goal_review']['requirements'][0]['tasks'], [{'module_id': 'M001', 'task_id': 'T1'}])
        self.assertEqual(review['goal_review']['requirements'][0]['path_ids'], ['P1'])  # GP1 names no requirement
        self.assertEqual(review['modules'][0]['checks']['changes']['evidence_refs'], [files['audit-change-inventory.md']])
        with self.assertRaisesRegex(Rejected, 'unfilled skeleton field left in audit-code-review.json'):
            f.call('audit-code-review', {'report_ref': files['audit-code-review.json']}, role='auditor', module=None)
        inventory = out / 'audit-change-inventory-filled.md'; inventory.write_text(filled(text))
        proof = f.ref('diff.patch', 'before/after')
        review.update(auditor_instance_id='auditor', change_inventory_ref=file_ref(inventory))
        for m in review['modules']:
            m['diff_refs'] = [proof]
            for check in m['checks'].values():
                check.update(conclusion='satisfied', reason='compared with the inventory')
        for row in review['goal_review']['requirements']:
            row.update(conclusion='satisfied', reason='goal met')
        f.call('audit-code-review', {'report_ref': f.ref('review-filled.json', review)}, role='auditor', module=None)
        self.assertEqual(f.state()['audit_code_review']['change_inventory_ref'], file_ref(inventory))
        with self.assertRaisesRegex(Rejected, 'refusing to overwrite'):
            report_skeleton.write(f.root, out)


if __name__ == '__main__':
    unittest.main()
