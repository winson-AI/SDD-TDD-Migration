---
description: /sdd-module <run-id> <module-id> — 推进单模块实现与自测闭环
---

# /sdd-module

## 1. 用法
`/sdd-module <run-id> <module-id>`

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 前置门控：模块已冻结；依赖满足或可记录 dependency Yellow；目标 baseline 和锁可验证。推进前运行 `verify_openspec.py --root <run> --scope module --module-id <module-id>`，核验本模块、祖先与实际依赖。失败按 recovery_action 处理相关范围，无关模块继续；核验不取代当前 assignment 与派发门禁。见 [核验范围](sdd-verify.md)。
3. 按 `status` 游标派发对应角色，推进 Coding→代码接受→build 派发（派发内 building 预检）→构建结果接受→automation 派发（派发内 testing 预检）。可修复 Red/Yellow 在累计预算内诊断并派发 Fixer；补丁接受后先重建再自动化，两环节共用模块修复预算。全部路径有效 Green 后检查 DoD。确认依赖/外围阻塞或预算耗尽时记录根因/memory，等待宿主统一审计；遇人工阻塞或预算上限保存 checkpoint 退出。

## 3. 调用契约
目标角色：[Module-Orchestrator](../Agents/module-orchestrator.md)。

## 4. 对应规格
[模块守卫](../skills/migration-protocol/references/state-machine.md#module-orchestrator-唯一模块守卫)、[有限循环](../skills/migration-protocol/references/state-machine.md#有限循环)。

## 上下文就绪门禁

worker 接到派发后按阶段提交预检：Implementer 提交 coding；Test Runner 分别提交 building（构建）和 testing（自动化）；Fixer 提交 fixing。ready 报告绑定派发后才可写代码或执行测试，blocked 报告退回派发、不消耗修复轮次。详见 [阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)。

## 本地实现接入

MO assign → worker submit → MO accept → complete。

本命令推进已有 run 内的一个已注册模块。用户指定已划分的独立功能模块来启动完整迁移时，应在同一项目入口使用 `/sdd-init --mode single-module --module-name "功能模块名"`（自动读取已保存项目配置），由 GO 识别根范围与需求/CASE 后初始化，再由 sdd-plan 推进叶子 TASK、六件套、上游用例路径及冻结，然后使用本命令或 sdd-run；后续仍须 Auditor 收尾。

本命令依据节点类型推进：父 MO 先认领 GO 的 scope/context 后拆子模块并看护迁移，子 MO 认领子 scope/context 后拆 tasks、独立实现；父节点负责管理与汇总。single-module 的“单”限定一个根功能，子功能仍由独立子 MO 执行。

Test-Runner 先 test_scope=build，再 automation。仅自动化环境不可用时，按 status 游标提交 automation-unavailable，保存 Yellow/未执行，继续其他任务；不可停留在 blocked 预检空等。见 [双环节协议](../skills/migration-protocol/references/build-automation.md#4-自动化环境缺失直接记-yellow-并继续)。
