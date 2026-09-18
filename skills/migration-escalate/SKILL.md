---
name: migration-escalate
description: 结构化人工阻塞、反馈转机器输入和超时升级，用于 SDD-TDD-Migration 的 Escalation 任务。
---

# migration-escalate

## 1. 定位
服务 Escalation；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/runtime.md)。

## 2. 核心规约
每个问题包含影响、证据、尝试、选项和推荐；决定绑定 question_id、run/module、revision 和内容 hash。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：逐个展示阻断问题，记录人类原话和结构化答案，交守卫确认后再恢复。

禁止：把等待超时当默认同意；自动替用户签字；复用失效版本的批准。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
问题自包含；真实答复引用；过期决定拒绝；超时仍 pending；恢复不直接置 Green。

## 6. 配套资产
使用 [主要模板](../../template/human-decision.json)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。
