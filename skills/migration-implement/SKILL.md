---
name: migration-implement
description: 冻结任务驱动的 legacy 迁移、新架构实现和双向追溯，用于 SDD-TDD-Migration 的 Implementer 任务。
---

# migration-implement

## 1. 定位
服务 Implementer；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/openspec.md)。

## 2. 核心规约
先确定需求/接口/数据差异，再逐任务迁移最小实现；记录保真策略和批准的行为差异；只读 legacy。

所有跨层输入输出通过 Ledger 已提交引用传递；本技能不授予角色之外的写权限。

## 3. 标准模式
推荐：TASK-M001-001 → REQ/CASE → target 文件与 code baseline；反向从每个改动文件能找到任务。

禁止：复制旧架构到目标绕过新边界；缺 tasks 就临时扩大任务；未生成代码便运行测试。

## 4. 接口契约
输入 assignment_ref + event_ref + absolute artifact refs；输出角色权限矩阵许可的事件及模板工件。文件已生成不等于已接受，必须收到 Ledger ACK。

## 5. 检查
冻结/锁有效；静态检查与单测证据真实；所有代码变动有任务；未越权更新规范。

## 6. 配套资产
使用 [主要模板](../../template/implementation.md)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

实施补充：依据 source_closure 和 target_feasibility 逐项闭合真实生产路径，检查入口、依赖注入、消费方和外部结果，不能以接口声明、样例实现或资源文件存在替代生产接线。提交 stage-result，带全部 TASK→文件追溯及 production_binding_evidence；优先恢复本角色原会话，始终重验当前 freeze。

依据冻结的复用映射完成依赖/DI/生产接线与适配，提交 reuse_trace 和实际解析版本证据；不因外部源码可读便复制或修改整个来源项目。reference-only 与真实运行依赖明确区分。见 [二方库复用协议](../migration-protocol/references/reuse-dependencies.md)。

无法直接复用时，按当前功能和已知上下文，结合存量源码、新架构与目标现状继续实现 adapt/reference/new；更换冻结方案先走 CR。仅核验替代实现也不可行时，通过 Ledger 提交证据交 MO 审阅并生成“未实现”提醒，不用占位实现冒充交付。入口与核验材料见该协议第 8 节。
