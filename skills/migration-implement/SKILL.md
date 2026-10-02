---
name: migration-implement
description: 冻结任务驱动的 legacy 迁移、新架构实现和双向追溯，用于 SDD-TDD-Migration 的 Implementer 任务。
---

# migration-implement

## 1. 定位
服务 Implementer；先读取 [共享协议](../migration-protocol/SKILL.md)，再按阅读卡读 [职责协议](../migration-protocol/references/openspec.md) 的相应小节。

## 2. 核心规约
先确定需求/接口/数据差异，再逐任务迁移最小实现；记录保真策略和批准的行为差异；只读 legacy。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：TASK-M001-001 → REQ/CASE → target 文件与 code baseline；反向从每个改动文件能找到任务。

禁止：复制旧架构到目标绕过新边界；缺 tasks 就临时扩大任务；未生成代码便运行测试。

## 4. 接口契约
见 [共享协议·通用约定](../migration-protocol/SKILL.md#通用约定)。

## 5. 检查
冻结/锁有效；静态检查与单测证据真实；所有代码变动有任务；未越权更新规范；`authoring_diagnostics` 已提交（诊断通过，或不可用时版本敏感 API 引用固定版本源码）。

## 6. 配套资产
使用 [主要模板](../../template/implementation.md)；其他工件用游标步骤 `templates` 列出的模板。无项目执行器时按 Yellow 处理，不能生成假测试结果。

角色义务、必交证据与专题入口以 [Agent 定义](../../Agents/implementer.md#专题义务) 为准；本技能只保留执行规约与检查，不重复专题细则。
