---
description: /sdd-retrospect <run-id> [lessons.json绝对路径] — 留存同任务教训并采集跨 Run 经验
---

# /sdd-retrospect

run 结束且 retrospective_due 时，drive 把复盘派给统一 Auditor；Auditor（或宿主）用 `report_skeleton.py --root <run_root> --retrospective --out <staging>` 取 Ledger 预填观察的骨架，按 [retrospective.json](../template/retrospective.json) 写完适用条件、根因、策略、结果和下次检查，提交全局 retrospect(lessons_ref)；无可抽象时提交 retrospect(nothing_to_abstract=理由)。ACK 后自动采集；交付不等复盘，未交的在 package-feedback 记为欠账。门禁及复用边界见 [跨运行经验](../skills/migration-protocol/references/project-context.md#跨运行经验沉淀与复用)。

只重采已有事实时用 experience.py harvest --root <workspace>/.sdd-migration --run-root <原run>；失败可重试，不改变业务状态、预算或测试结果。
