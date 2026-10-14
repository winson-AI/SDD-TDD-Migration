---
description: /sdd-status <run-id> — 冷读全局与模块状态
---

# /sdd-status

## 1. 用法
`/sdd-status <run-id>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：事实日志可读；投影缺失/过期只由 Ledger 重建。
3. 只读汇总：各模块 phase/execution_status/quality、Red/Yellow 路径与根因、依赖、预算与 next_action；不触发测试、修复或推进，不伪造事件回执。

## 3. 契约与规格
目标角色 [Ledger](../Agents/ledger.md)；[编排游标](../skills/migration-protocol/references/local-runtime.md#编排游标)、[进度信号](../skills/migration-protocol/references/progress-recovery.md#3-宿主必须消费的进度信号)。

## 4. 接入要点
- 视图：`--view cursor`（模块摘要、步骤、module_rounds、进度信号）；`--view step --module <id>`（本步、预检要求、分配包，规划步另带 planning_context）；`--view module --module <id>`；`--view full` 只供脚本。quality 是全局聚合，须分别展示各模块；await-all-module-rounds 时按 continue_modules 继续、wait_for_modules 等待，不把等待审计回写为失败。
- 同时展示 module_rounds 清单与 blockers、父 MO 统一名、`<run_root>/reports/migration-report.md/.json`（运行中标 in-progress）、`workflow_progress.state/signals/runnable_actions/worker_watches`；`notify_user=true` 时告知受影响模块、owner、原因与下一步；`reason=not-implemented` 时突出未实现项与所需人工决策。来源追加时展示 source_change_next_step 与评审引用，不把全局等待当作模块失败。
- 投影巡检用 `verify_openspec.py --scope projection`（与 status 分开）；OpenSpec 入口为顶层 `openspec/runs/<run_id>/workflow.md`，缺失说明未 prepare，不能当作完成。恢复与调度由宿主按[进度恢复协议](../skills/migration-protocol/references/progress-recovery.md#总则)执行。
