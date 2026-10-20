---
name: migration-fix
description: 最小修复、回归证据与不改变验收的变更建议，用于 SDD-TDD-Migration 的 Fixer 任务。
---

# migration-fix

## 1. 定位
服务 Fixer；[职责协议](../migration-protocol/references/testing.md)。

## 2. 核心规约
修复目标是满足已冻结契约；修改验收/任务定义先 CR，不能边改标准边证明通过。

## 3. 标准模式
推荐：以 diagnosis 和失败 PATH 编写最小补丁，自回归后交正式 Test-Runner/Auditor。

禁止：删除断言、放宽阈值或直接改质量状态；未经锁写跨模块公共文件。

## 4. 接口契约
见[通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
补丁范围明确；回滚/影响完整；回归记录真实；验收标准未越权改变；`authoring_diagnostics` 已随补丁提交。

## 6. 配套资产
使用 [主要模板](../../template/change-request.md)。

角色硬约束以 [Agent 定义](../../Agents/fixer.md#6-硬约束) 为准；专题规则由阅读卡按触发列出、按需读取。
