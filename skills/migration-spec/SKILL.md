---
name: migration-spec
description: OpenSpec 六件套、plan 澄清冻结和 CR 影响分析，用于 SDD-TDD-Migration 的 Spec-Designer 任务。
---

# migration-spec

## 1. 定位
服务 Spec-Designer；先读取 [共享协议](../migration-protocol/SKILL.md)，再按阅读卡读 [职责协议](../migration-protocol/references/openspec.md) 的相应小节。

## 2. 核心规约
使用真实 delta specs，需求 ID 与 Scenario 可追溯；测试验收先于实施确定；tasks 原子可执行。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：用 manifest 绑定六件套定义和测试设计，再接受可追溯的人类决定与 MO 冻结事件。

禁止：把 status/checklist 说成 OpenSpec 内置功能；只冻结文件名不冻结内容；修复时直接改验收。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
六件套与全局契约对应；每个问题有决定；任务有范围/依赖/证据；变更重新冻结。

## 6. 配套资产
使用 [主要模板](../../template/freeze.json)；其他工件用游标步骤 `templates` 列出的模板。无项目执行器时按 Yellow 处理，不能生成假测试结果。

角色义务、必交证据与专题入口以 [Agent 定义](../../Agents/spec-designer.md#专题义务) 为准；本技能只保留执行规约与检查，不重复专题细则。
