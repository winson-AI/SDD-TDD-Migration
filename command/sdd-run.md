---
description: /sdd-run <run-id> — 并行推进就绪模块
---

# /sdd-run

消费 status.run_change_next_step，按 [同 Run 修订](../skills/migration-protocol/references/progress-recovery.md#同-run-上游修订) 推进；规划读取 history_refs，审计预算用 audit-recover，不另建 Run。

待应用来源追加时消费 status.source_change_next_step：Host 协调当前 worker 完成后再更新当前上下文，不取消无关 MO；若进度使评审过期，GO 重读后重新提交具体影响。切换完成后，受影响叶子回到规划，无关模块用新阶段上下文继续原冻结任务。参考 [来源追加协议](../skills/migration-protocol/references/source-changes.md#2-host上下文调整与明确恢复)，不要用旧 input.json 替代 Ledger 当前快照。

## 1. 用法
`/sdd-run <run-id>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：run 已初始化；可调度工作存在；宿主提供隔离实例/身份与单写 Ledger；max_parallel_modules 合法。先以 `verify_openspec.py --root <run> --scope global` 核验公共基础，再对当前派发目标用 `--scope module --module-id <id>` 检查其祖先与实际依赖。局部失败只处理关联范围，无关 ready MO 继续；核验不证明宿主真实派发。见 [核验范围](sdd-verify.md)。
3. 按 `status` 游标派发对应角色。就绪模块在依赖与写集合约束内并行；仅已冻结模块可以编码。按 module_id 分别消费事件，单个失败不取消或标失败其他 MO；继续就绪模块并等待仍在执行的模块。完整 registry 中全部模块完成或各自明确挂起、无活动 worker 与可推进动作后，才请求独立审计。暂时没有 ready 动作不代表运行中的 MO 已结束。

## 3. 调用契约
目标角色：[Global-Orchestrator](../Agents/global-orchestrator.md)。

## 4. 对应规格
[模块隔离与全量收尾](../skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)、[编排游标](../skills/migration-protocol/references/local-runtime.md#编排游标)。

## 本地实现接入

Global 选择 ready 模块 → MO assign/accept。

编排读取 `status.next_steps` 与 `global_next_step`，按 ready/reason 决定下一动作；`mechanical=true` 的步骤（全绿测试结果的 accept、执行派发的 assign）用 `ledger.py advance` 以 MO 身份一次提交；用 session_id 恢复对应角色，只传事件和工件引用。ready 只是当前快照建议，提交时必须带 expected_revision 再过门禁；阻塞或预算不足不能自行跳步。

当前策略：本地优先修复一轮，确认依赖/外围或一轮未通过则 audit-defer 并退出。Global 必须等待全部模块本轮 completed 或明确挂起，且没有活动 worker/可推进动作，再统一 audit-collect。正常依赖解除和已有批准的 resume 先执行；不能仅因当前没有 worker 就拉起 Auditor。

活动批次按 finding 路由、按依赖交错修复与 Testing，失败仅挂起关联分支。部分成功汇总后待人工；audit-release 需要当前报告摘要批准。主循环及 subagent/skills 调用均由宿主执行，Ledger 返回游标并在每次提交复核门禁。

宿主逐 module_id 收集结果并重读 Ledger；单次异常只归属该模块，继续 ready 模块并等待活动实例。不得因全局颜色或 global_next_step.ready=false 批量关闭模块。

父子模式下 next_steps 也包含父节点的 decompose/decompose-accept/module-summary；GO 负责接受拆分，父 MO 负责拆分与当前版本汇总。不能只等待 status.modules（叶子），还必须检查 module_groups 和完整 module_rounds。

## 上下文预检调度

先读步骤的 context_gate（预检要求全文在 `--view step` 的 `context`）。worker 派发不等预检：派发后由该 worker 在同一会话内 context-submit，ready 后开工；blocked 报告退回派发（reason=context-blocked），补齐后重新提交或由 MO 按自身证据挂起。审计派发因 context-readiness-required 未就绪时，宿主先启动 Auditor 预检；`with_operation=true` 的报告随原操作提交。不得因 ready=false 停止补上下文或提前审计。详见 [阶段协议](../skills/migration-protocol/references/context-readiness.md#5-缺失失效与恢复)。

## 命名与收尾信号

宿主创建父 MO 时按父步骤的 agent_name 命名为 parent-mo-M<编号>。本轮收尾后 GO 必须提供全部测试用例状态清单，非 Green 附原因和证据，不能仅给“已完成”一句话；复用 `<run_root>/reports/migration-report.md` 与 `.json`，遵守 [报告协议](../skills/migration-protocol/references/migration-report.md#总则)。
