---
name: migration-spec
description: OpenSpec 六件套、plan 澄清冻结和 CR 影响分析，用于 SDD-TDD-Migration 的 Spec-Designer 任务。
---

# migration-spec

## 1. 定位
服务 Spec-Designer；先读取 [共享协议](../migration-protocol/SKILL.md)，再读 [职责协议](../migration-protocol/references/openspec.md)。

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
使用 [主要模板](../../template/freeze.json)；其他工件由 [模板索引](../../template/INDEX.md) 定位。无项目执行器时按 Yellow 处理，不能生成假测试结果。

实施补充：冻结前核实最小源码闭环（入口→事件/状态→数据/平台→可观察结果）和目标能力/依赖证据。把允许路线和禁止变化写入 decision_envelope；外部证据只引用 path/hash，不把源码全文复制进 OpenSpec。初始批准与当前执行版本分开记录，边界内任务修订仍经 MO 发布新 freeze。

保持测试设计提前；本地 SPEC 定义须包含合法 delta heading 与 requirement/scenario。Ledger 自动物化六件套及动态视图；改变定义提交新 plan/CR，不直接改生成文件。

复用目录与需求语义对齐后，把提供方、差异适配、接线和验证写进 design/tasks/checklist；以 stage-plan.reuse_plan_ref 冻结映射，原始需求仍控制验收。见 [二方库复用协议](../migration-protocol/references/reuse-dependencies.md)。

## 四维语义落入 OpenSpec

读取 [四维协议](../migration-protocol/references/dimension-slicing.md)，先协助划定任务范围，再生成绑定 scope 的任务四维分析，将具体实现指导、分配 item ID、可观察行为、目标差异及验证映射写入 design/spec/tasks；dimension_analysis_ref + dimension_trace 与六件套一起冻结。

领域知识按 [lean 工程纪律](../migration-protocol/references/lean-disciplines.md) 通过受限 knowledge-query/foundation-resolve 读取与解析；把适用结果或明确 not-required 绑定计划，不完整加载 Lean skill。UI 树遵守原生 bindings/events/dynamicRules 对象、capabilities 对象和 attachments 列表；source-only 仍严格验 source/tree，声明手势冻结完整动作与预期。

在已有 test-design 中按 [状态测试表](../../template/ui-state-test-design.md) 区分稳定截图目标和瞬态行为。未知资源如实记录 manual_exact/blocked；每个源资源/qualifier 独立映射，多消费者及跨配置路由按 [资源接入](../migration-protocol/references/lean-integration.md#资源执行与事实绑定) 留证。外部能力目录只提名方案，遵从结果的 sdd_adaptation_ref，将决策写入现有 SPEC/四维项。

source-only 手势可绑定 automation，仍冻结完整动作/起点/预期，不创建假视觉基线。逐适用资源变体核对 collector、实际源文件与 Resource item 的同一 hash；有证据的范围外变体用 resource_scope.exclusions，不能省略已启用配置。详见 [UI 保真](../migration-protocol/references/ui-fidelity.md)。
