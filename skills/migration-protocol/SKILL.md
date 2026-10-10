---
name: migration-protocol
description: SDD-TDD-Migration 各角色共享的读取、Ledger、冻结和三态契约；用于本工作流运行及恢复。
---

# 共享协议

## 1. 定位
共享最小契约。步骤卡/步骤视图之外按需取单节，不整份加载协议或状态。

## 2. 核心规则
遵守[四条红线](../../AGENTS.md#四条红线)。Ledger 单写者负责持久化，Module-Orchestrator 决定模块业务迁移，Global-Orchestrator 决定跨模块调度，Auditor 决定独立审计结论，职责不能互换。并行 MO 的状态与结果彼此独立；单模块失败不向无关模块传播，全局聚合颜色不回写模块。Auditor 等完整 registry 中全部模块本轮结束后统一启动。

## 3. 模式
assignment → 摘要绑定当前输入 → 职责内工件 → 请求 → ACK → 事件引用后退出。编排器限预算循环；无 ACK 仅 staged。发现问题先以 `issue` 登记给适用模块再继续；只有必然使构建或已有用例失败的才标 blocks。

## 4. 取用
- 规则：阅读卡外用 reading.py show --ref <文件> --section <小节> 取单节。
- 状态：ledger.py status --view step --module <id>；全局省略 module。含步骤、信封、预检、分配和 assignment，规划另带 planning_context；不读 full。
- 摘要：contracts.py ref/baseline/digest 分别取文件、代码基线和 JSON 摘要，不用 shasum 替代。

## 5. 检查
确认角色身份/assignment、Ledger sequence、输入 hash、权限范围；拒绝占位符或伪造证据；失败和受阻均记录可恢复动作。

## 6. 资产
阅读卡 templates 实例化到本实例 staging，不覆盖包模板。

## 7. 业务边界与阶段验收

GO/MO 切分垂域，四维表示边界，叶子 SPEC 约束 Implementer；MO 审核冻结，真实未决或需求/验收/授权变化才交人工，技术协调经 Ledger。流程见[控制主线](references/state-machine.md#控制主线)。模块测试归 MO、审计结论归 Auditor；正式完整 Green 且门禁满足直接记录，无额外会签。覆盖、修复和验收 owner 分开，见[阶段验收](references/testing.md#分阶段唯一验收-owner)。

## 通用约定

适用于全部角色定义，角色文件不再逐份重复。

- 优先级：用户/宿主 → [红线](../../AGENTS.md#四条红线) → 项目规则 → 阅读卡 → 默认实践；旧 guidance 冲突见 README 覆盖表。
- 输入为已提交 assignment、绝对 path+sha256；读取核 hash。职责内 operation/工件写本实例 staging，ACK 后才接受。
- 跨层只走 Ledger。叶子结束即退出，编排限预算；不静默覆盖，保留 history 及失败。
- 缺输入/权限/工具提交 reason_code/root_cause/next_action；人工交 Escalation，跨模块依赖交 GO，不凭摘要继续。总线失联报 transport failure 后停机，产物仍 staged。
- 输出格式（传输摘要不是质量判定，Green/Red/Yellow 以 Ledger 有效证据为准）：

```text
✅ submitted | event_id=<id> | artifacts=<绝对路径> | next=<账本动作>
⚠️ suspended | event_id=<id> | reason=<原因> | next=<恢复条件>
❌ failed | event_id=<id或transport-unavailable> | reason=<失败原因>
```

## 8. 专题规则

见 AGENTS.md 专题索引，按当前事实取单节。来源变化不清除失败、重置预算或批准代码。
