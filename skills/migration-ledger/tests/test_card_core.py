"""A card's always-on core is small; the general sections that apply to some roles or runs ride only there."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import reading


class CardCoreTests(unittest.TestCase):
    def test_the_core_is_the_red_lines_and_the_shared_rules(self):
        self.assertEqual(reading.CORE, [('AGENTS.md', '四条红线')] + [(reading.SHARED, h) for h in
                                                                  ('2. 核心规则', '3. 模式', '4. 取用', '5. 检查', '通用约定')])
        core = sum(len(reading.section(path, heading).encode()) for path, heading in reading.CORE)
        self.assertLess(core, 3_500)

    def test_general_sections_ride_where_they_apply(self):
        runtime, storage, boundary = reading.P + 'runtime.md', reading.P + 'storage-layout.md', (reading.SHARED, '7. 业务边界与阶段验收')
        coder = reading.entries('implementer')
        self.assertNotIn((runtime, '总则'), coder); self.assertNotIn((runtime, '渐进加载'), coder); self.assertNotIn(boundary, coder)
        self.assertIn((storage, '总则'), coder)
        orchestrator = reading.entries('module-orchestrator', operation='assign')
        for item in ((runtime, '总则'), (runtime, '渐进加载'), boundary):
            self.assertIn(item, orchestrator)
        self.assertNotIn((storage, '总则'), orchestrator)
        self.assertIn(boundary, reading.entries('escalation')); self.assertIn(boundary, reading.entries('auditor', operation='audit-plan'))
        self.assertIn((runtime, '渐进加载'), reading.entries('implementer', operation='session'))  # whoever resumes a session

    def test_readiness_rides_only_on_a_run_that_requires_it(self):
        step = {'role': 'module-orchestrator', 'operation': 'assign'}
        keys = lambda s: {(row['ref'], row['section']) for row in reading.card(s, None, step)}
        self.assertIn((reading.P + 'context-readiness.md', '总则'), keys({'context_readiness_required': True}))
        self.assertNotIn((reading.P + 'context-readiness.md', '总则'), keys({}))


if __name__ == '__main__':
    unittest.main()
