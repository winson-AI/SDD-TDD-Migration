# 宿主接入契约:如何真实走完控制流

本文件回答一个问题:**怎样才算"宿主真实执行了本控制流",而不是手写文件模拟。** 它把散落在各 reference 里的"宿主负责……"整合成逐阶段、可执行、可自证的清单。

宿主必须同时满足两条：(1) 每一步通过 `ledger.py`/`project_context.py` 提交事件，遵守状态守卫，不手写状态或投影；(2) 各角色由宿主真实派发并完成职责内工作。事件链记录已提交的动作，但 hash 链不能证明外部执行发生。[verify_openspec.py](../../migration-ledger/scripts/verify_openspec.py) 只核验指定范围的记录/投影一致性；真实派发、代码修改、构建和设备执行须宿主回执与独立审查证据。

## 1. 宿主必须提供、控制器不代劳的三件事

1. **身份认证与 host-context 注入**:每次 `apply`/`init` 传入认证过的 `{"role":..,"instance_id":..}`;绝不能让请求体自报 role 获得权限,也不能让 worker 自选 host-context。
2. **真实派发 Agent**:控制器只记录 dispatch 请求并在 `status.next_steps` 给出游标;宿主必须用自己的 task/spawn 工具,按 [Agents/*.md](../../../Agents/) 定义启动隔离实例,并把结果经 Ledger 回传。控制器不 spawn、不嵌套 slash command。
3. **真实工作落地**:Implementer/Fixer 真写 `target_root` 源码;Test-Runner 经 [execute_test.py](../../migration-ledger/scripts/execute_test.py) 调项目真实构建/测试命令;Auditor 独立实例真实重跑。`code_files`/`checks_passed`/断言都由宿主真实产生,不能自填冒充。

这三件事无法从控制器内部强制(CLI 非安全边界);它们是本契约要求宿主自证的核心。

## 2. 逐阶段接入清单

每行:命令 → 必须提交的 Ledger op → 宿主必须做的真实工作 → 如何自证。所有 op 语义见 [本地运行指南](local-runtime.md) 操作矩阵。

| 命令 | 必须提交的 Ledger op(顺序) | 宿主真实工作 | 自证 |
| --- | --- | --- | --- |
| `/sdd-init` | `project_context.py prepare` → `ledger.py init`(payload 带 `project_context_ref`)→ `register`(拓扑序)→ `global-plan` | 认证 host;GO 生成功能清单/切片/覆盖;真实规范/架构/用例引用 | `status.openspec_binding.location==top-level`;`events.jsonl` 逐条增长;顶层 `openspec/runs/<run_id>/workflow.md` 出现 |
| `/sdd-plan` | (树形先 `decompose`→`decompose-accept`)→ `plan`(Spec-Designer)→ `freeze`(MO,绑定真实 `decision_id` 或 within-envelope) | 派发 Spec-Designer 真实产出六件套;人工澄清冻结决定 | `changes/<run-id>-<mid>/` 六件套 + `manifest.json` 由投影生成;freeze 事件绑定真实 `human_source_ref` |
| `/sdd-run`、`/sdd-module` | `assign`/`submit`/`accept`(implementer)→ `assign`/`submit`/`accept`(test-runner:先 build 后 automation)→ 需要则 `diagnose`/`diagnosis-accept`/`assign(fixer)` → `complete`;父节点 `module-summary` | 派发各角色隔离实例;真写 target 代码;execute_test 跑真实命令;真实 diff/DoD 审查 | 每 assignment 有 submit+accept;`code_baseline` 与磁盘一致(否则 `observed_invalidations` 报警);`complete` 前全 PATH Green |
| `/sdd-audit` | `audit-code-review` → `audit-collect` → `audit-plan` → `audit-route-batch` → `audit-work`/`audit-retest` → `audit-verdict`(→`audit-release`) | **独立** Auditor 实例(≠ 任何 implementer/fixer/test 作者)真实重跑;Fixer 按路由修复 | `authors` 独立性校验通过;audit 报告绑定当前 snapshot;`audit-reports/<batch>.md` 生成 |
| `/sdd-archive` | 宿主 OpenSpec CLI 同步/归档(无 Ledger `archive` op) | 人工交付授权;代码合并另行授权 | `verify_openspec --scope final` 通过 + 原归档质量门禁;归档不等于合并 |
| `/sdd-status`、`/sdd-verify` | 只读,不提交事件 | —— | 核验范围适合当前动作；planning 的 projection 通过不代表 completed |

## 3. 接入自检(部署一次,证明编排器真接了 Ledger)

在一次性 throwaway workspace 上执行,确认产生的是**真实事件**而非手写文件:

```sh
# 1. 最小管道:确认控制器被真实调用、投影落顶层
python3 <pkg>/skills/migration-ledger/scripts/project_context.py prepare --root <ws>/.sdd-migration --request <req.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py init   --root <ws>/.sdd-runs/<run> --request <init.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py status  --root <ws>/.sdd-runs/<run>   # 断言 openspec_binding.location==top-level
python3 <pkg>/skills/migration-ledger/scripts/verify_openspec.py --root <ws>/.sdd-runs/<run> --scope global  # 仅断言公共记录/布局一致
```

- **管道自证**:上面四步后,`ledger/events.jsonl` 必须存在且逐条增长;若你的编排器"跑完"却没有 events.jsonl,或只有 `module-registry.json`/散文报告,就是**没接 Ledger**,必须修接线。
- **派发自证**:让编排器真实执行一次 `/sdd-plan <run> <mid>`,检查新出现的 `plan` 事件 `actor` 是被派发的 spec-designer 实例、`plan_ref` 指向该 Agent 产出的工件——而不是编排器自己写的。同理 implement 阶段检查 `code_files` 确由 Implementer 写入 `target_root`。
- **接线参照**:[simulate_storage.py](../../migration-ledger/tests/simulate_storage.py) 调用真实 prepare/Ledger/执行器，可作为接线对照与冒烟骨架；其中审批、角色和业务输入是测试夹具，不证明用户授权、真实 Agent 派发或移动设备验证。

## 4. 判定与红线

- 全局调度前用 `--scope global`；逐模块规划/派发用 `--scope module --module-id <id>`；全量视图巡检用 `--scope projection`；GO 最终交付/归档前用 `--scope final`。默认 projection 兼容旧只读调用，但不能用全量失败停止无关模块。按返回的 failures.scope/module_id/recovery_action 修复相关范围，公共事件链/快照损坏才影响整轮。
- `status.openspec_binding.location==in-run-fallback` 表示未绑定预备布局,OpenSpec 落在 run 内——按未接入处理。
- 控制器校验结构、绑定、摘要和已有执行回执，不能仅从自报字段证明语义正确或独立执行；宿主身份/权限约束、实际执行回执与独立 Auditor 审查共同承担这一责任。不得把 `verified=true` 或工具 exit 0 当作功能通过。
- `observed_invalidations` 非空说明目标代码被 out-of-band 修改,须 revoke→invalidate 重走,不得无视继续。

完整存储不变量与门禁细节见 [留存布局](storage-layout.md#openspec-投影完整性收尾门禁);操作矩阵见 [本地运行指南](local-runtime.md);阶段守卫见 [状态机](state-machine.md)。

## 5. 领域工具接线

宿主交接优先读取 `openspec/runs/<run_id>/workflow.json` 的 routing/模块索引、相关 module state 与工件引用。派发前刷新 Ledger status 校验 sequence/revision；不要在每次交接复制完整 Ledger、所有兄弟模块日志或整套领域 skill。Agent 仍能通过当前快照、六件套、父级分配和实际依赖引用访问全局存量/目标源码、架构与知识；紧凑交接不能裁掉完成任务需要的上下文。快照引用失效或 routing_refresh_required 时按既有恢复动作更新，不创建第二份调度状态。

按 [lean 受限接入](lean-integration.md) 将白名单操作映射到现有角色，不创建第二套编排游标或冻结权威。Spec-Designer 分析 UI；Implementer/Fixer 在 assignment 与写范围内精确转换资源；Test-Runner/Auditor 在当前 assignment 下取证和比较，构建仍走正式执行器。[设备与模型工具](visual-execution.md) 需要冻结的 run 环境配置、实际设备锁证明及当前 PATH 构建/基线，工具本身不验收；模型请求有总时限，缺条件沿原 Yellow 通道。Host 传认证 host-context，保留原始结果引用、转换证据和正式 Ledger payload；所有新增输出落本 run 受管目录。

prepared run 的 `ui_fidelity_required=true`、`spec_closure_required=true`（每个拆分模块一条 static PATH，位于 build 与 automation 之间），仅 applicable UI 触发对应门禁；无 UI 不制造空视觉任务。仅自动化不可用继续按 Yellow/未执行收尾，独立任务与可用构建下游不受阻。

## 提示采纳回报

游标的 `session_id`/`session_affinity` 与 `must_read`/`card_sha256` 是建议。宿主派发 worker 时在 assign payload 回填实际恢复或新建的 `session_id` 和交给角色的 `card_sha256`；Ledger 只记录与建议是否一致（`status.hint_adoption`），不据此拒绝派发。持续的 not_followed 或 unreported 说明宿主未落实冷启动优化，应在接入层修正，而不是放宽门禁。
