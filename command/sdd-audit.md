---
description: /sdd-audit <run-id> — 整体代码审查、代码治理与独立遗留复核
---

# /sdd-audit

## 1. 用法
`/sdd-audit <run-id>`

## 2. 编排步骤
1. 先按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)。
2. 前置门控：完整 registry 中所有 MO 本轮完成或基于自身证据明确挂起，无活动 worker、无可推进动作（手工调用也不跳过等待，不为审计强制结束其他 MO）；审计实例与实现/修复/脚本作者分离；未生成的代码只报告 Yellow。
3. 按 global_next_step 派发：先 audit-code-review（[代码治理协议](../skills/migration-protocol/references/audit-code-review.md#顺序与职责)，必须提交[本次代码修改清单](../template/audit-change-inventory.md)并由 change_inventory_ref 绑定），治理发现先委派修正；再 audit-collect → audit-plan → audit-route-batch → owner MO audit-work → Fixer → Test-Runner → audit-retest → audit-verdict；失败分支待人工，独立分支继续；汇总后批准 audit-release；仅剩未验证路径才执行测试，不重跑有效 Green，不追加全量测试。

## 3. 契约与规格
目标角色 [Auditor](../Agents/auditor.md)；[审计范围](../skills/migration-protocol/references/audit-scope.md#总则)、[Auditor 与全局完成](../skills/migration-protocol/references/state-machine.md#auditor-与全局完成)。

## 4. 接入要点
- 预检：audit-analysis/audit-verdict 随 audit-plan/audit-verdict 提交；audit-assign 有待测路径时先 context-submit audit-testing，空清单时为 audit-verdict。见[阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)。
- 审计失败后的下一步是 audit-route / repair-accept，不立即循环 audit-assign；模块修复复测完成后才开下一轮，报告关联上一轮非 Green 的 test_run_id。global_paths 可为空。
- 纯自动化缺测不是必须修复的缺陷：全量收尾后汇总缺测 PATH，环境仍不可用时 audit-unavailable 留 Yellow 结束本轮，不宣称 Green。见[双环节协议](../skills/migration-protocol/references/build-automation.md#5-auditor-与恢复)。
- 全量阅读前 `verify_openspec.py --scope projection`，GO 交付前 `--scope final`（报告须 completed 或 completed-with-unverified-tests）；核验通过不证明真实派发或全部 Green。
