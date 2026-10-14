---
description: /sdd-run <run-id> — 并行推进就绪模块
---

# /sdd-run

## 1. 用法
`/sdd-run <run-id>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：run 已初始化、存在可调度工作、宿主能提供隔离实例与单写 Ledger、max_parallel_modules 合法。先 `verify_openspec.py --scope global` 核验公共基础，再对派发目标用 `--scope module --module-id <id>`；局部失败只处理关联范围，见[核验范围](sdd-verify.md)。
3. 按 `status` 游标派发：就绪模块在依赖与写集合约束内并行，仅已冻结模块可编码；逐 module_id 消费事件，单个失败不取消其他 MO；父节点的 decompose/decompose-accept/module-summary 同样出现在 next_steps，须同时检查 module_groups 与 module_rounds。全部模块完成或各自明确挂起、无活动 worker 与可推进动作后，才请求独立审计；暂时没有 ready 动作不代表运行中的 MO 已结束。

## 3. 契约与规格
目标角色 [Global-Orchestrator](../Agents/global-orchestrator.md)；[编排游标](../skills/migration-protocol/references/local-runtime.md#编排游标)、[模块隔离与全量收尾](../skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 4. 接入要点
- `mechanical=true` 的步骤用 `ledger.py advance` 以 MO 身份一次提交；用 session_id 恢复角色，只传事件与工件引用；提交带 expected_revision 再过门禁，阻塞或预算不足不跳步。
- 本地先修复一轮，确认依赖/外围或一轮未通过则 audit-defer 退出；正常依赖解除与已批准的 resume 先执行，不因当前没有 worker 就拉起 Auditor。
- 同 Run 修订消费 status.run_change_next_step（[同 Run 修订](../skills/migration-protocol/references/progress-recovery.md#同-run-上游修订)）；来源追加消费 source_change_next_step，当前 worker 完成后再更新上下文，不取消无关 MO（[来源追加协议](../skills/migration-protocol/references/source-changes.md#2-host上下文调整与明确恢复)）。
- 预检：worker 派发后在同一会话 context-submit，ready 开工，blocked 退回派发；审计派发未就绪时先启动 Auditor 预检。见[阶段协议](../skills/migration-protocol/references/context-readiness.md#5-缺失失效与恢复)。
- 父 MO 按父步骤 agent_name 命名（parent-mo-M<编号>）；收尾时 GO 提供全部测试用例状态清单，复用 `<run_root>/reports/migration-report.md/.json`，见[报告协议](../skills/migration-protocol/references/migration-report.md#总则)。
