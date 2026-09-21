---
name: migration-protocol
description: SDD-TDD-Migration 各角色共享的读取、Ledger、冻结和三态契约；用于本工作流运行及恢复。
---

# 共享协议

## 1. 定位
所有角色先读本入口，具体规则按职责读取引用，避免全量加载角色说明。

## 2. 核心规则
遵守 [全包红线](../../AGENTS.md)。Ledger 单写者负责持久化，Module-Orchestrator 决定模块业务迁移，Global-Orchestrator 决定跨模块调度，Auditor 决定独立审计结论，职责不能互换。并行 MO 的状态与结果彼此独立；单模块失败不向无关模块传播，全局聚合颜色不回写模块。Auditor 等完整 registry 中全部模块本轮结束后统一启动。

## 3. 模式
接受 assignment → 读取版本绑定的输入 → 产生职责内工件 → 提交事件 → 等待 ACK → 输出事件引用后退出。编排器可在预算内重复该过程。未收到 ACK 的产出仅为 staged，不构成上游完成。

## 4. 契约入口
- 所有人读取 [runtime.md](references/runtime.md)：路径、事件、权限、传输、恢复。
- 编排器、Ledger、Auditor 读取 [state-machine.md](references/state-machine.md)：状态、门禁、聚合、预算。
- Spec-Designer、Implementer、Fixer 读取 [openspec.md](references/openspec.md)：中间表示、版本冻结、变更和归档。
- Test-Runner、Diagnostician、Fixer、Auditor 读取 [testing.md](references/testing.md)：query、assert、三态和复测。

## 5. 检查
确认角色身份/assignment、Ledger sequence、输入 hash、权限范围；拒绝占位符或伪造证据；失败和受阻均记录可恢复动作。

## 6. 资产
[模板索引](../../template/INDEX.md)；全部实例化路径按运行协议解析，不能直接覆盖包内模板。

## 7. 业务边界与阶段验收

各角色在其职责及已批准 scope 内执行；跨模块或不确定的业务边界必须经 Ledger/Escalation 交人工决定。已批准边界内的调度、修复和复测按协议推进。模块测试由对应 MO 唯一验收，审计测试由对应 Auditor 唯一验收；正式完整 Green 且既有门禁满足后直接记录，无额外人工会签。覆盖归属、修复 owner 与验收 owner 分开，细则见 [测试契约](references/testing.md)。

## 8. 持久化项目上下文

宿主、Global 与 Ledger 读取 [project-context.md](references/project-context.md)：首次保存、用户增量更新、运行 prepare 固化及 Ledger 绑定。模块角色只使用本轮快照和已提交输入引用；配置更新不覆盖旧运行，也不替代边界决策/冻结/验收。

## 9. 父子 MO 与共同上下文

两种入口只限定迁移范围；父 MO 拆分子功能、独立子 MO 执行、父 MO 汇总。父子均须读取全局存量/目标代码、架构规范、知识及最新分工。涉及规划/拆分/收尾时必读 [父子 MO 协议](references/module-decomposition.md)。

## 10. 二方库与已有能力

GO/父子 MO、Spec Designer、Implementer、Testing/Fixer/Auditor 涉及规划、编码和验证时读取 [reuse-dependencies.md](references/reuse-dependencies.md)：TARGET/外部来源、功能语义抽取、需求映射、冻结接入指导与版本变化后的复测。复用是重要的规划依据，不能替代需求与完整测试。

复用必须逐行为对齐存量源码功能并保证 fidelity：记录源码基线、差异和复现 PATH/ASSERT；冻结后编码、Main 留证、对应 MO/Auditor 验收。具体记录及门禁见该协议第 7 节。

不能直接复用时，结合当前功能、上下文、源代码与目标现状推进适配或自主 Coding；只有核验替代方案仍不可行才走“未实现”人工提醒，见该协议第 8 节。

目标已有实现也要与二方库核对；确认冗余且可复用/适配时，直接重构目标依赖、调用链并清理重复逻辑，沿用冻结和正式测试门禁，不重复造轮子。职责节点及完成准则见该协议第 9 节。

## 11. 阶段上下文就绪

规划、派发、恢复或审计前读取 [上下文就绪协议](references/context-readiness.md)：实际执行者先提交身份/版本绑定的核对报告，原节点接受后推进；报告 ready 不替代冻结、权限、正式测试或 DoD。

## 12. 编译构建与自动化分流

GO/MO、Spec Designer、Test-Runner、Fixer、Auditor 与宿主必读 [build-automation.md](references/build-automation.md)。同一 Test-Runner 先构建再自动化；仅自动化环境缺失可 Yellow 收尾并放行其他可执行任务，质量验收不变 Green。

## 13. 四维完整性

GO、父/子 MO、Spec-Designer 在规划时，以及 Implementer/Fixer/Test-Runner/Auditor 在执行/验收时读取 [dimension-slicing.md](references/dimension-slicing.md)：有序分析、条件 N/A、父子完整覆盖与 OpenSpec/TASK/PATH/ASSERT 追溯。

## 14. 局部恢复与进度信号

宿主、GO/MO 与 Ledger 在调度、等待或恢复时必读 [progress-recovery.md](references/progress-recovery.md)：运行期局部校验、invalidate 历史保留与重规划出口、workflow_progress 人工信号及自动化缺测收尾。禁止在 ready=false 或命令拒绝后无提示地退出。

## 15. Auditor 代码治理

所有 MO 收尾后，先按 [整体代码治理](references/audit-code-review.md) 独立审查全部代码修改、冗余、二方库及公共能力，委派治理和受影响完整回归，再处理剩余 Red/Yellow。Auditor 不兼代码作者；新增任务/接口/边界仍走 CR 与重新冻结。

## 16. 来源与 provider 版本变化

GO/父子 MO/Host 在运行中追加只读来源时读 [source-changes.md](references/source-changes.md)：GO 完整影响评审、Host 绑定批准与新快照事务、相关阻塞恢复及无关模块证据延续。v2 显式 owner、资源锁与 provider 变更闭环见 [复用协议第 10 节](references/reuse-dependencies.md#10-显式-provider-归属与合法版本变更)。来源变化不自动清除失败、重置预算或批准代码。
