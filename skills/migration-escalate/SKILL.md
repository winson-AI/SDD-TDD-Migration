---
name: migration-escalate
description: 结构化人工阻塞、反馈转机器输入和超时升级，用于 SDD-TDD-Migration 的 Escalation 任务。
---

# migration-escalate

## 1. 定位
服务 Escalation；[职责协议](../migration-protocol/references/runtime.md)。

## 2. 核心规约
每个问题包含影响、证据、尝试、选项和推荐；决定绑定 question_id、run/module、revision 和内容 hash。

## 3. 标准模式
推荐：逐个展示阻断问题，记录人类原话和结构化答案，交守卫确认后再恢复。

禁止：把等待超时当默认同意；自动替用户签字；复用失效版本的批准。

## 4. 接口契约
见[通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
问题自包含；真实答复引用；过期决定拒绝；超时仍 pending；恢复不直接置 Green。

## 6. 配套资产
使用 [主要模板](../../template/human-decision.json)。
