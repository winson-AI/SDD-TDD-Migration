---
name: migration-audit
description: 独立遗留复核、快照冻结、修复委派与最终裁决，用于 SDD-TDD-Migration 的 Auditor 任务。
---

# migration-audit

## 1. 定位
服务 Auditor；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/state-machine.md)。

## 2. 核心规约
等待所有 MO 实现/测试本轮收尾及父汇总，然后从 Ledger 收集 Red/Yellow。读取对应 SPEC/CASE/PATH/根因，复核并委派必要的一轮 Fixer，修复后 Testing 复核；失败留根因待人工。作者与审计实例分离。

**遍历全部模块不等于重跑全部用例。** 有效且不受影响的 Green 保留证据；global_test_paths 可为空，绝不能阻止审计。执行选择、空清单独立审阅及旧 run 恢复必须遵守 [审计范围协议](../migration-protocol/references/audit-scope.md)。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：全部模块本轮完成或明确挂起且无可推进工作后，统一扫描并行遗留 → 读取发现/负责模块 SPEC 和测试路径 → 根因路由 → MO 委派一轮 Fixer → 独立 Testing 复核 → 成功裁决；失败记录根因待人工，禁止重复自动修复。

禁止：直接修改代码/测试；只接受 Fixer 回归日志；拿旧基线 Green 拼成全局全绿。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
全模块遍历；遗留及受影响回归留证；同一最终基线；所有遗留问题显示；达到上限如实升级。

## 6. 配套资产
使用 [主要模板](../../template/audit-report.md)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

本地非 Green 审计产生 audit_repairs，由 Global 路由、MO 接受重开；下一轮保留 audit_results 的非 Green retest_of 链。详见 [控制流闭环](../migration-protocol/references/local-runtime.md#控制流闭环修订)。

默认收尾扫描全部模块，使用 audit-collect/audit-plan/audit-route-batch/audit-work/audit-retest/audit-verdict；失败问题及依赖下游生成 audit-reports/<batch-id>.md/json 待人工，独立分支继续；汇总后由批准的 audit-release 进入受控恢复。problem-* 只保留兼容。收尾只复核待验证清单；清单为空则独立 audit-review，不启动自动化。详见 [当前运行契约](../migration-protocol/references/local-runtime.md)。

按 finding_id 路由，支持不同问题分别修复及单问题多 owner；按依赖交错 Testing，不等待全批 owner。宿主实际启动 subagent 与 Used Skills。

Auditor 是审计范围 CASE/PATH 的唯一验收 owner；正式复测完整 Green、证据有效且覆盖门禁满足即直接记录审计结论，无额外会签。MO 保留模块执行守卫。新增跨模块或不确定业务边界交人工决定；不得以多 repair owner 推导多人共同验收。

审计读取语义目录、需求映射和实际二方库版本，按依赖图验证共享提供方与受影响消费者；不越权修改外部来源，失败输出根因待人工。见 [复用协议](../migration-protocol/references/reuse-dependencies.md)。
