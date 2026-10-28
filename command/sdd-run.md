---
description: /sdd-run <run-id> — 并行推进就绪模块
---

# /sdd-run

## 1. 用法
`/sdd-run <run-id>`

## 2. 编排步骤
1. 先按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)。
2. 前置门控：run 已初始化、存在可调度工作、宿主能提供隔离实例与单写 Ledger、max_parallel_modules 合法。先 `verify_openspec.py --scope global` 核验公共基础，再对派发目标用 `--scope module --module-id <id>`；局部失败只处理关联范围，见[核验范围](sdd-verify.md)。
3. 循环执行 `drive.py --root <run> --host-context '<MO 身份>' --wait <秒>`（[宿主循环](../skills/migration-protocol/references/host-integration.md#宿主循环)），只读它输出的行，不读状态视图：
   - `dispatch`：按 role 启动隔离实例，交 card 路径；带 session_id 时接续该会话。
   - `running`：Ledger 已派的 worker；未启动则按 card 与 instance_id 启动，已启动则等待。
   - `host`：宿主按 operation 与 payload 自行提交。
   - `person`：交 Escalation 按 detail 问人，决定绑定 approval_subject_sha256。
   - `signal`：按 next_action 处理；severity=human 时告知用户。同一信号只印一次，tick 行的 signals_held 是仍成立的旧信号数。
   - `done`：run 到终点（质量、原因、报告路径）；停止循环，把报告交给用户，green 时请其授权交付，带未验证用例时列出这些用例。
   - `tick`：本轮结束，回到循环。
   机械步骤、并行上限、依赖与审计时机由 Ledger 守卫，宿主不自行判断；单个失败不取消其他模块。

## 3. 契约与规格
目标角色 [Global-Orchestrator](../Agents/global-orchestrator.md)；[编排游标](../skills/migration-protocol/references/local-runtime.md#编排游标)、[模块隔离与全量收尾](../skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 4. 接入要点
- 角色只拿到 card 与事件/工件引用；提交带 expected_revision 再过门禁，阻塞或预算不足不跳步。
- 本地先修复一轮，确认依赖/外围或一轮未通过则 audit-defer 退出；正常依赖解除与已批准的 resume 先执行，不因当前没有 worker 就拉起 Auditor。
- 同 Run 修订（[同 Run 修订](../skills/migration-protocol/references/progress-recovery.md#同-run-上游修订)）与来源追加（[来源追加协议](../skills/migration-protocol/references/source-changes.md#2-host上下文调整与明确恢复)）也以 drive 行出现；当前 worker 完成后再更新上下文，不取消无关 MO。
- 预检：worker 派发后在同一会话 context-submit，ready 开工，blocked 退回派发；审计派发未就绪时先启动 Auditor 预检。见[阶段协议](../skills/migration-protocol/references/context-readiness.md#5-缺失失效与恢复)。
- 父 MO 按父步骤 agent_name 命名（parent-mo-M<编号>）；收尾时 GO 提供全部测试用例状态清单，复用 `<run_root>/reports/migration-report.md/.json`，见[报告协议](../skills/migration-protocol/references/migration-report.md#总则)。
