---
name: migration-spec
description: OpenSpec 六件套、plan 澄清冻结和 CR 影响分析，用于 SDD-TDD-Migration 的 Spec-Designer 任务。
---

# migration-spec

## 1. 定位
服务 Spec-Designer；[职责协议](../migration-protocol/references/openspec.md)。

## 2. 核心规约
使用真实 delta specs，需求 ID 与 Scenario 可追溯；测试验收先于实施确定；tasks 原子可执行。

## 3. 标准模式
推荐：子 MO 拆 TASK 后直接以 manifest 绑定六件套和上游用例路径，MO 审核冻结；design 按需协助，执行中遗漏/fidelity 问题走局部 CR 再冻结，真实未决或语义变化才需 Human。

禁止：把 status/checklist 说成 OpenSpec 内置功能；只冻结文件名不冻结内容；修复时直接改验收。

## 4. 接口契约
见[通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
六件套与全局契约对应；每个问题有决定；任务有范围/依赖/证据；变更重新冻结。

## 6. 配套资产
使用 [主要模板](../../template/stage-plan.json)。

角色硬约束以 [Agent 定义](../../Agents/spec-designer.md#6-硬约束) 为准；专题规则由阅读卡按触发携带。
