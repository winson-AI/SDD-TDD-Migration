"""A run whose host stopped is noticed without a host and continued by a new one from a written handover."""
import os
from pathlib import Path
import sys
import time
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import handover
import test_ledger
import test_watchdog
import watchdog
from contracts import Rejected


class HandoverTests(unittest.TestCase):
    def test_the_handover_names_what_is_ready_open_and_drafted(self):
        f = test_ledger.FlowTests(methodName='runTest'); f.setUp(); self.addCleanup(f.doCleanups)
        f.global_plan()
        old = f.root / 'staging/spec-designer/sd-old/spec.md'; old.parent.mkdir(parents=True); old.write_text('done')
        os.utime(old, (time.time() - 86400, time.time() - 86400))  # written before the last event: not unsubmitted work
        draft = f.root / 'staging/spec-designer/sd-m001/spec.md'; draft.parent.mkdir(parents=True)
        draft.write_text('- **GIVEN** [[待写：前置条件]]\n')
        out = handover.brief(f.root)
        self.assertEqual([(r['module_id'], r['operation']) for r in out['ready_actions']], [('M001', 'plan')])
        self.assertEqual([(r['dir'], r['unfilled']) for r in out['unsubmitted_staging']], [('staging/spec-designer/sd-m001', 1)])
        self.assertEqual(out['open_assignments'], [])
        text = Path(out['path']).read_text()
        self.assertIn('M001: plan (spec-designer)', text); self.assertIn('sd-m001: 1 files, 1 [[待写 left', text)


class ScheduleTests(unittest.TestCase):
    def test_the_scheduled_check_is_a_line_for_the_person_to_install(self):
        w = test_watchdog.WatchdogTests(methodName='runTest'); w.setUp(); self.addCleanup(w.doCleanups)
        line = watchdog.schedule(w.root, 10)
        self.assertTrue(line['cron'].startswith('*/10 * * * * '))
        self.assertIn('watchdog.py check --root ' + str(w.root), line['cron'])
        with self.assertRaisesRegex(Rejected, '1..59'):
            watchdog.schedule(w.root, 0)


if __name__ == '__main__':
    unittest.main()
