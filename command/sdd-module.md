---
description: /sdd-module <run-id> <module-id> — 推进单模块实现与自测闭环
---

# /sdd-module

## 1. 用法
`/sdd-module <run-id> <module-id>`

## 2. 编排步骤
1. 先按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)。
2. 前置门控：模块已冻结、依赖满足或可记 dependency Yellow、目标 baseline 与锁可验证；先 `verify_openspec.py --scope module --module-id <module-id>`，失败按 recovery_action 处理相关范围，见[核验范围](sdd-verify.md)。
3. 按游标推进 Coding → 代码接受 → build 派发（building 预检）→ 构建接受 → automation 派发（testing 预检）；可修复 Red/Yellow 在累计预算内诊断并派 Fixer，补丁接受后先重建再自动化；全部路径 Green 后检查 DoD；确认依赖/外围阻塞或预算耗尽则记根因等待统一审计，人工阻塞保存 checkpoint 退出。

## 3. 契约与规格
目标角色 [Module-Orchestrator](../Agents/module-orchestrator.md)；[模块守卫](../skills/migration-protocol/references/state-machine.md#module-orchestrator-唯一模块守卫)、[有限循环](../skills/migration-protocol/references/state-machine.md#有限循环)。

## 4. 接入要点
- 本命令推进已注册模块：父 MO 认领 scope/context 后拆子模块并看护，子 MO 拆 tasks 独立实现。要从一个独立功能启动完整迁移，用 `/sdd-init --mode single-module --module-name "功能模块名"`，再 sdd-plan、本命令或 sdd-run，最后 Auditor 收尾。
- `execute_test.py` 不传 `--adapter` 时按 PATH 取冻结 command 或 `test_adapter.adapters[platform]`。
- 预检按阶段提交：Implementer coding 与 Fixer fixing 由 Ledger 在派发时写出，Test-Runner building 与 testing（命令全冻结时也由 Ledger 写）；Fixer 自报 blocked 退回派发并退还修复轮次。Test-Runner 先 test_scope=build 再 automation，自动化环境不可用时提交 automation-unavailable 保存 Yellow 继续，不空等。见[阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)、[双环节协议](../skills/migration-protocol/references/build-automation.md#4-自动化环境缺失直接记-yellow-并继续)。
