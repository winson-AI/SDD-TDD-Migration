"""The Ledger writes the executing roles' report skeletons; a report that still holds a mark is refused."""
import json
import subprocess
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
        self.assertEqual(set(files), {'preflight-testing.json', 'static-review.json'}); self.assertGreater(result['unfilled'], 10)
        pre = json.loads(check_ref(files['preflight-testing.json']).read_text())
        s = f.state(); plan = s['modules']['M001']['plan']
        self.assertEqual(pre['subject_sha256'], cr.subject(s, 'M001', 'testing'))
        self.assertEqual(set(pre['execution']['commands']), {'S1', 'P1'})  # the review goes ahead of the automation in one dispatch
        self.assertIn(SKELETON_MARK, pre['execution']['commands']['S1']['argv'][0])
        self.assertEqual(pre['checks']['frozen-spec']['status'], 'ready'); self.assertIn(SKELETON_MARK, pre['checks']['test-environment']['status'])
        with self.assertRaisesRegex(Rejected, 'unfilled skeleton field left in preflight-testing.json'):
            f.raw('context-submit', {'report_ref': files['preflight-testing.json']}, role='test-runner', instance='test-runner')
        proof = f.ref('probe.md', 'JDK and SDK probed on this host')
        for name in ('provider-binding', 'test-environment', 'permissions-tools'):
            pre['checks'][name] = {'status': 'ready', 'summary': 'probed on this host', 'evidence_refs': [proof]}
        pre['execution']['commands'] = {'S1': {'argv': t.static_argv(), 'cwd': str(f.target)},
                                        'P1': {'argv': [sys.executable, str(f.base / 'adapter.py')], 'cwd': str(f.target)}}
        pre['execution'].update(argv=t.static_argv(), cwd=str(f.target))  # the review is this dispatch's first command
        pre['execution']['environment_ref'] = f.ref('test-env.md', 'Python test fixture'); pre['verdict'] = 'ready'
        ref = f.ref('preflight-filled.json', pre)
        f.raw('context-submit', {'report_ref': ref}, role='test-runner', instance='test-runner')
        self.assertEqual(f.state()['modules']['M001']['context_receipts']['testing:test-runner']['report_ref'], ref)
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
        row = next(line for line in text.splitlines() if line.startswith('| M001 / C1 | P1 /'))
        self.assertNotIn(report_skeleton.SKELETON_MARK, row)  # the test mapping is what the Ledger holds: nothing to write
        self.assertIn('必测：TASK T1；在当前代码上运行', row)
        self.assertIn(Path(s['modules']['M001']['results']['P1']['execution_receipt']['path']).name, row)
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


# The marks of the unified code review by leaf count on a Git target, last recorded in VERIFICATION.md.
RECORDED_MARKS = {2: 40, 10: 144, 30: 404}


class GitChangeTests(unittest.TestCase):
    """With a target that is a Git checkout, what the inventory's file rows and the review's diffs say is what Git says."""
    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True, capture_output=True, text=True)

    def test_each_file_is_an_add_or_a_modify_with_its_lines_and_diff(self):
        import tempfile
        from contracts import file_ref
        target = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(__import__('shutil').rmtree, target, True)
        (target / 'kept.kt').write_text('a\nb\nc\n'); self.git(target, 'init', '-q'); self.git(target, 'add', '-A'); self.git(target, 'commit', '-q', '-m', 'start')
        start = self.git(target, 'rev-parse', 'HEAD').stdout.strip()
        (target / 'kept.kt').write_text('a\nB\nc\n'); (target / 'new.kt').write_text('x\ny\n')
        context = target.parent / (target.name + '-context.json'); context.write_text(json.dumps({'target_commit': start}))
        self.addCleanup(context.unlink)
        s = {'target_root': str(target), 'project_context_ref': file_ref(context),
             'modules': {'M001': {'code_files': [file_ref(target / 'kept.kt'), file_ref(target / 'new.kt')]}}}
        out = Path(tempfile.mkdtemp()); self.addCleanup(__import__('shutil').rmtree, out, True)
        changes = report_skeleton.git_changes(s, out)
        kept, new = changes['files'][str(target / 'kept.kt')], changes['files'][str(target / 'new.kt')]
        self.assertEqual((kept['kind'], kept['before'], kept['lines']), ('modify', 'kept.kt', '2-2'))
        self.assertEqual(kept['before_sha'], self.git(target, 'rev-parse', start + ':kept.kt').stdout.strip()[:12])
        self.assertEqual((new['kind'], new['before'], new['before_sha'], new['lines']), ('add', '不适用', '不适用', '1-2'))
        diff = check_ref(changes['modules']['M001']).read_text()
        self.assertIn('-b', diff); self.assertIn('+B', diff); self.assertIn('+x', diff)
        self.assertIsNone(report_skeleton.git_changes({**s, 'project_context_ref': None}, out))  # no start: the Auditor writes these

    def test_a_prepared_run_on_a_git_target_records_its_start_and_its_skeleton_takes_what_git_says(self):
        import test_context_readiness
        import test_continuous_run
        real = test_context_readiness.ContextReadinessTests.setUp
        def setup(t):
            real(t)
            (t.target / '.keep').write_text(''); self.git(t.target, 'init', '-q'); self.git(t.target, 'add', '-A'); self.git(t.target, 'commit', '-q', '-m', 'start')
        test_context_readiness.ContextReadinessTests.setUp = setup
        self.addCleanup(setattr, test_context_readiness.ContextReadinessTests, 'setUp', real)

        class Walk(test_continuous_run.ContinuousWalk):
            def model_turn(self, step):
                if step.get('operation') == 'audit-code-review':
                    raise StopIteration
                super().model_turn(step)
        w = Walk(methodName='run'); w.setUp(); self.addCleanup(w.doCleanups)
        with self.assertRaises(StopIteration):
            w.walk(80)
        s = w.f.state()
        self.assertEqual(report_skeleton.target_start(s), self.git(w.f.target, 'rev-parse', 'HEAD').stdout.strip())
        files = report_skeleton.write(w.f.root, w.f.root / 'staging/auditor/review')['files']
        text = check_ref(files['audit-change-inventory.md']).read_text()
        rows = [line for line in text.splitlines() if line.startswith('| CHG-0')]
        self.assertTrue(rows and all('| add | 不适用 |' in row and 'diffs/' in row for row in rows), rows)
        review = json.loads(check_ref(files['audit-code-review.json']).read_text())
        self.assertTrue(all(m['diff_refs'][0]['path'].endswith(m['module_id'] + '.diff') for m in review['modules']))
        self.report_growth(w.f.root)

    def report_growth(self, root):
        """The marks the Auditor fills in one turn as leaves are added (copies of a completed leaf): reported, not a gate."""
        import copy, tempfile, warnings
        import ledger
        s = {**ledger.read_events(root)[0], 'run_root': str(root)}
        leaf, mark, taken = next(iter(s['modules'].values())), report_skeleton.SKELETON_MARK, {}
        for n in RECORDED_MARKS:
            state = copy.deepcopy(s)
            state['modules'].update({'M%03d' % (100 + i): {**copy.deepcopy(leaf), 'module_id': 'M%03d' % (100 + i)} for i in range(n - len(s['modules']))})
            out = Path(tempfile.mkdtemp()); self.addCleanup(__import__('shutil').rmtree, out, True)
            changes = report_skeleton.git_changes(state, out)
            text = report_skeleton.inventory(state, 1, changes) + json.dumps(report_skeleton.code_review(state, {'path': 'inventory', 'sha256': 'x'}, changes), ensure_ascii=False)
            taken[n] = text.count(mark)
        if any(taken[n] > RECORDED_MARKS[n] for n in taken):
            warnings.warn('the unified code review holds %s marks by leaves, %s recorded' % (taken, RECORDED_MARKS))
