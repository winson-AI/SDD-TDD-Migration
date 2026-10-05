---
description: /sdd-retrospect <run-id> [lessons.json绝对路径] — 留存同任务教训并采集跨 Run 经验
---

# /sdd-retrospect

读取原 Run 已提交证据，按 [retrospective.json](../template/retrospective.json) 提炼适用条件、根因、策略、结果和下次检查；宿主写自身 staging，提交全局 retrospect(lessons_ref)，ACK 后自动采集。门禁及复用边界见 [跨运行经验](../skills/migration-protocol/references/project-context.md#跨运行经验沉淀与复用)。

只重采已有事实时用 experience.py harvest --root <workspace>/.sdd-migration --run-root <原run>；失败可重试，不改变业务状态、预算或测试结果。
