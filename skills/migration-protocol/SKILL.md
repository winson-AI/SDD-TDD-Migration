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

## 通用约定

适用于全部角色定义，角色文件不再逐份重复。

- 规则优先级：当前用户与宿主约束 → [AGENTS.md](../../AGENTS.md) 四条红线 → 项目明确规则 → Used Skills → 默认技术实践。旧 guidance 冲突按本包 README 覆盖表处理。
- 输入输出：全部为 [运行协议](references/runtime.md) 定义的绝对路径/事件引用；内容产出在本实例 staging，读取已提交工件须验证 hash。
- 跨层信息：只走 Ledger；叶子角色完成 assignment 即退出，编排角色仅按批准预算继续。工件不得静默覆盖，旧版本和失败证据必须保留。
- 阻塞与异常：缺关键输入、权限或工具时提交 reason_code/root_cause/next_action；若需人类，交 Escalation；若为跨模块依赖，交 Global。只经 Ledger，不凭摘要直接继续。无法提交 Ledger 时输出 transport failure 并停机，工件保持 staged，不能称已记录。
- 输出格式（传输摘要不是质量判定，Green/Red/Yellow 以 Ledger 有效证据为准）：

```text
✅ submitted | event_id=<id> | artifacts=<绝对路径> | next=<账本动作>
⚠️ suspended | event_id=<id> | reason=<原因> | next=<恢复条件>
❌ failed | event_id=<id或transport-unavailable> | reason=<失败原因>
```

## 8. 专题规则

专题规则（项目上下文、父子 MO、二方库与 fidelity、上下文就绪、构建与自动化、四维切片、恢复、Auditor 代码治理、来源变化、埋点、资产布局、UI 领域工具）不在此重复，按 [AGENTS.md 专题索引](../../AGENTS.md#专题索引) 的触发条件读取对应小节；阅读卡会带上适用的部分。来源变化不自动清除失败、重置预算或批准代码。
