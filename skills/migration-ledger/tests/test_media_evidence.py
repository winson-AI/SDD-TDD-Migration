"""Media a test kept beside its verdict: hash-bound inside the run, listed per path in the report, handed to whoever diagnoses or fixes."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import migration_report
import test_ledger
from contracts import Rejected, file_ref, media_evidence


class MediaEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = f = test_ledger.FlowTests(); f.setUp(); self.addCleanup(f.doCleanups)

    def media(self, name='final.mp4', kind='recording', where='runs/harmony/automation/attempt-1'):
        path = (self.f.root / where / name).resolve(); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'media ' + name.encode())
        return {'kind': kind, 'ref': file_ref(path)}

    def test_media_rows_are_hash_bound_files_of_known_kinds_inside_the_output(self):
        good = self.media()
        self.assertEqual(media_evidence([good]), [good])
        self.assertEqual(media_evidence([good], self.f.root / 'runs'), [good])
        with self.assertRaisesRegex(Rejected, 'media_refs are'):
            media_evidence([{'kind': 'gif', 'ref': good['ref']}])
        with self.assertRaisesRegex(Rejected, 'outside the execution output'):
            media_evidence([good], self.f.root / 'runs/build')
        with self.assertRaises(Rejected):
            media_evidence([{'kind': 'recording', 'ref': {**good['ref'], 'sha256': 'f' * 64}}])

    def test_a_result_keeps_its_media_and_the_report_and_the_diagnosis_read_them(self):
        f = self.f; f.prepare(); f.implementation()
        a, result = f.make_test_result(quality='red-bug')
        result['paths'][0]['media_refs'] = [self.media(), self.media('final_snapshot.png', 'screenshot')]
        f.submit(result, a); f.call('accept', {'assignment_id': a['assignment_id']})
        state = f.state()
        self.assertEqual([m['kind'] for m in state['modules']['M001']['results']['P1']['media_refs']], ['recording', 'screenshot'])
        step = state['next_steps'][0]
        self.assertEqual((step['operation'], sorted(step['media_evidence'])), ('diagnose', ['P1']))
        report = migration_report.build(f.root, state, state['last_sequence'])
        row, = [r for r in report['paths'] if r['path_id'] == 'P1']
        self.assertEqual([m['kind'] for m in row['media_refs']], ['recording', 'screenshot'])
        text = migration_report.render(report)
        self.assertIn('recording final.mp4；screenshot final_snapshot.png', text); self.assertIn('- 媒体（recording）', text)
        previous = result['paths'][0]['test_run_id']
        a2, bad = f.make_test_result(aid='TEST2', quality='red-bug', previous=previous)
        bad['paths'][0]['media_refs'] = [{'kind': 'clip', 'ref': self.media('clip.mp4')['ref']}]
        with self.assertRaisesRegex(Rejected, 'media_refs are'):
            f.submit(bad, a2)
        elsewhere = (f.base / 'elsewhere/final.mp4'); elsewhere.parent.mkdir(parents=True, exist_ok=True); elsewhere.write_bytes(b'x')
        bad['paths'][0]['media_refs'] = [{'kind': 'recording', 'ref': file_ref(elsewhere)}]
        with self.assertRaisesRegex(Rejected, 'outside the execution output'):
            f.submit(bad, a2)

    def test_record_video_is_a_flag_of_an_automation_or_visual_path(self):
        import test_functional_paths
        import test_validation as tv
        t = test_functional_paths.FunctionalPathTests(); t.setUp(); self.addCleanup(t.doCleanups)
        plan = t.f.plan(); tv.plan_check(plan, str(t.f.target))
        other = next(p for p in plan['paths'] if p['kind'] in ('build', 'unit')); other['record_video'] = True
        with self.assertRaisesRegex(Rejected, 'record_video is a flag'):
            tv.plan_check(plan, str(t.f.target))
        other.pop('record_video'); next(p for p in plan['paths'] if p['path_id'] == 'P1')['record_video'] = True
        tv.plan_check(plan, str(t.f.target))  # the flow keeps its walk on film beside the verdict


if __name__ == '__main__':
    unittest.main()
