---
name: migration-fix
description: 最小修复、回归证据与不改变验收的变更建议，用于 SDD-TDD-Migration 的 Fixer 任务。
---

# migration-fix

## 1. 定位
服务 Fixer；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/testing.md)。

## 2. 核心规约
修复目标是满足已冻结契约；修改验收/任务定义先 CR，不能边改标准边证明通过。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：以 diagnosis 和失败 PATH 编写最小补丁，自回归后交正式 Test-Runner/Auditor。

禁止：删除断言、放宽阈值或直接改质量状态；未经锁写跨模块公共文件。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
补丁范围明确；回滚/影响完整；回归记录真实；验收标准未越权改变。

## 6. 配套资产
使用 [主要模板](../../template/change-request.md)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

修复结果必需 fix_note_ref，使用 [fix-note 模板](../../template/fix-note.json)。读取 module memory.md / ledger repair-memory.json，经事件引用核对适用条件；只有正式回归 verified 条目可当已验证策略参考，仍需本轮测试。
