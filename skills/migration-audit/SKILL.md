---
name: migration-audit
description: 整体代码审查、重构/复用治理委派、独立遗留复核与最终裁决，用于 SDD-TDD-Migration 的 Auditor 任务。
---

# migration-audit

## 1. 定位
服务 Auditor；[职责协议](../migration-protocol/references/state-machine.md)。

## 2. 核心规约
等所有 MO 本轮收尾及父汇总后，先按 [整体代码治理](../migration-protocol/references/audit-code-review.md#顺序与职责) 提交 audit-code-review，核对全部代码改动、冗余、二方库依赖与公共能力，委派治理并完成影响范围回归、刷新审查，再从 Ledger 收集剩余 Red/Yellow：读对应 SPEC/CASE/PATH/根因，按已审 finding 路由委派 Fixer，修复后 Test-Runner 复核，可重试时沿累计预算继续，停滞或预算耗尽留根因待人工；作者与审计实例分离。

**遍历全部模块不等于重跑全部用例。** 有效且不受影响的 Green 保留证据；global_paths 可为空，绝不能阻止审计。执行选择、空清单独立审阅必须遵守 [审计范围协议](../migration-protocol/references/audit-scope.md#总则)。
无项目执行器时按 Yellow 处理，不能生成假测试结果。

本地非 Green 审计产生 audit_repairs，由 Global 路由、MO 接受重开；下一轮保留 audit_results 的非 Green retest_of 链。详见 [控制流闭环](../migration-protocol/references/state-machine.md#控制流闭环细则)。

按 finding_id 路由，支持不同问题分别修复及单问题多 owner；按依赖交错 Testing，不等待全批 owner。宿主实际启动 subagent 与 Used Skills。

审计读取语义目录、需求映射和实际二方库版本，按依赖图验证共享提供方与受影响消费者；不越权修改外部来源，失败输出根因待人工。见 [复用协议](../migration-protocol/references/reuse-dependencies.md#11-auditor-全局复用治理)。

## 3. 标准模式
推荐：整体代码审查 → 委派治理与受影响回归 → 刷新审查 → 收集遗留 → 根因路由 → MO 委派 Fixer → 独立 Test-Runner 复核 → 裁决；失败按实际影响、累计预算和停滞证据判断重试或人工介入。

禁止：直接修改代码/测试；只接受 Fixer 回归日志；拿旧基线 Green 拼成全局全绿。

## 4. 接口契约
见[通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
全模块遍历；遗留及受影响回归留证；同一最终基线；所有遗留问题显示；达到上限如实升级。

## 6. 配套资产
使用 [主要模板](../../template/audit-report.md)。
