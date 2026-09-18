---
name: migration-diagnose
description: 只读根因、依赖链与生成代码缺陷归因，用于 SDD-TDD-Migration 的 Diagnostician 任务。
---

# migration-diagnose

## 1. 定位
服务 Diagnostician；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/testing.md)。

## 2. 核心规约
区分 symptom、hypothesis、confirmed cause；读取实际日志与相关代码，定位归属与可复现步骤。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：报告 category=dependency、producer=M002、缺少 contract v2，并引用失败日志与 DAG 证据。

禁止：为了定位问题先修改源码；把外部超时武断归因产品 bug；无证据声称根因确认。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
证据与置信度齐全；责任范围明确；复现步骤具体；诊断过程没有代码修改。

## 6. 配套资产
使用 [主要模板](../../template/diagnosis.md)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

诊断补充：反馈必须包含 owner_module_id、owner_role、根因置信度、source/target 证据、受影响 PATH、建议 next_action 与是否可能改变 decision_envelope。owner 表示路由建议，MO 审核后派发，不赋予诊断者修改权限。

本地 diagnose 仅提交报告；MO diagnosis-accept 核验问题版本后推进阶段。诊断者不能自批，活动 worker 未关闭时不得提交。

二方库问题沿需求→能力映射→提供方版本→调用链→PATH 只读追踪，区分接线/适配缺陷与提供方/外围阻塞，保留影响消费者与根因证据。见 [复用协议](../migration-protocol/references/reuse-dependencies.md)。
