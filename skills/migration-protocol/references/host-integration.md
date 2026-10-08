# 宿主接入契约:如何真实走完控制流

本文件回答一个问题:**怎样才算"宿主真实执行了本控制流",而不是手写文件模拟。** 它把散落在各 reference 里的"宿主负责……"整合成逐阶段、可执行、可自证的清单。

## 总则

宿主要真实走完控制流，须遵守本契约：每步提交真实 Ledger 事件，各角色由宿主实际派发并执行。推进前按动作选择 `/sdd-verify` 范围：全局基础用 global，模块推进用 module（本模块、祖先和实际依赖），全量投影用 projection，最终交付用 final。只阻断核验失败的相关范围，不把无关模块错误扩散到全部 MO。核验仅证明记录与投影一致；真实派发、构建/设备执行和行为通过须各自的执行证据，不能由 hash 链证明。

## 1. 宿主必须提供、控制器不代劳的三件事

1. **身份认证与 host-context 注入**:每次 `apply`/`init` 传入认证过的 `{"role":..,"instance_id":..}`;绝不能让请求体自报 role 获得权限,也不能让 worker 自选 host-context。
2. **真实派发 Agent**:控制器只记录 assign 并在 `status.next_steps` 给出游标;宿主必须用自己的 task/spawn 工具,按 [Agents/*.md](../../../Agents/) 定义启动隔离实例,并把结果经 Ledger 回传。控制器不 spawn、不嵌套 slash command。
3. **真实工作落地**:Implementer/Fixer 真写 `target_root` 源码;Test-Runner 经 [execute_test.py](../../migration-ledger/scripts/execute_test.py) 调项目真实构建/测试命令;Auditor 独立实例真实重跑。`code_files`/断言都由宿主真实产生,不能自填冒充。

这三件事无法从控制器内部强制(CLI 非安全边界);它们是本契约要求宿主自证的核心。

## 2. 逐阶段接入清单

每行:命令 → 必须提交的 Ledger op → 宿主必须做的真实工作 → 如何自证。所有 op 语义见 [本地运行指南](local-runtime.md#操作矩阵) 操作矩阵。

| 命令 | 必须提交的 Ledger op(顺序) | 宿主真实工作 | 自证 |
| --- | --- | --- | --- |
| `/sdd-init` | `project_context.py prepare` → `ledger.py init`(payload 带 `project_context_ref`)→ `register`(拓扑序)→ `global-plan` | 认证 host;GO 生成功能清单/切片/覆盖;真实规范/架构/用例引用 | `status.openspec_binding.location==top-level`;`events.jsonl` 逐条增长;顶层 `openspec/runs/<run_id>/workflow.md` 出现 |
| `/sdd-plan` | scope/CASE 分配→叶子 TASK→Spec plan→MO freeze；design 按需 assign/submit/accept | SPEC 与上游用例路径、MO 技术审核及所需人工决定 | Ledger 补全 PATH/资产；CR 后更新 SPEC/已有代码；freeze 绑定当前审核 |
| `/sdd-run`、`/sdd-module` | `assign`/`context-submit`/`submit`/`accept`(implementer)→ 同序(test-runner:先 build 后 automation)→ 需要则 `diagnose`/`diagnosis-accept`/`assign(fixer)` → `complete`;父节点 `module-summary` | 派发各角色隔离实例;真写 target 代码;execute_test 跑真实命令;真实 diff/DoD 审查 | 每 assignment 有 submit+accept;`code_baseline` 与磁盘一致(否则 `observed_invalidations` 报警);`complete` 前全 PATH Green |
| `/sdd-audit` | `audit-code-review` → `audit-collect` → `audit-plan` → `audit-route-batch` → `audit-work`/`audit-retest` → `audit-verdict`(→`audit-release`) | **独立** Auditor 实例(≠ 任何 implementer/fixer/test 作者)真实重跑;Fixer 按路由修复 | `authors` 独立性校验通过;audit 报告绑定当前 snapshot;`audit-reports/<batch>.md` 生成 |
| `/sdd-archive` | 宿主 OpenSpec CLI 同步/归档(无 Ledger `archive` op) | 人工交付授权;代码合并另行授权 | `verify_openspec --scope final` 通过 + 原归档质量门禁;归档不等于合并 |
| `/sdd-status`、`/sdd-verify` | 只读,不提交事件 | —— | 核验范围适合当前动作；planning 的 projection 通过不代表 completed |

## 3. 接入自检(部署一次,证明编排器真接了 Ledger)

在一次性 throwaway workspace 上执行,确认产生的是**真实事件**而非手写文件:

```sh
# 1. 最小管道:确认控制器被真实调用、投影落顶层
python3 <pkg>/skills/migration-ledger/scripts/project_context.py prepare --root <ws>/.sdd-migration --request <req.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py init   --root <ws>/.sdd-runs/<run> --request <init.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py status --view full --root <ws>/.sdd-runs/<run>   # 断言 openspec_binding.location==top-level
python3 <pkg>/skills/migration-ledger/scripts/verify_openspec.py --root <ws>/.sdd-runs/<run> --scope global  # 仅断言公共记录/布局一致
```

- **管道自证**:上面四步后,`ledger/events.jsonl` 必须存在且逐条增长;若你的编排器"跑完"却没有 events.jsonl,或只有 `module-registry.json`/散文报告,就是**没接 Ledger**,必须修接线。
- **派发自证**:让编排器真实执行一次 `/sdd-plan <run> <mid>`,检查新出现的 `plan` 事件 `actor` 是被派发的 spec-designer 实例、`plan_ref` 指向该 Agent 产出的工件——而不是编排器自己写的。同理 implement 阶段检查 `code_files` 确由 Implementer 写入 `target_root`。
- **接线参照**:[simulate_storage.py](../../migration-ledger/tests/simulate_storage.py) 调用真实 prepare/Ledger/执行器，可作为接线对照与冒烟骨架；其中审批、角色和业务输入是测试夹具，不证明用户授权、真实 Agent 派发或移动设备验证。

## 4. 判定与红线

- 全局调度前用 `--scope global`；逐模块规划/派发用 `--scope module --module-id <id>`；全量视图巡检用 `--scope projection`；GO 最终交付/归档前用 `--scope final`。默认 projection；不能用全量失败停止无关模块。按返回的 failures.scope/module_id/recovery_action 修复相关范围，公共事件链/快照损坏才影响整轮。
- `status.openspec_binding.location==in-run-fallback` 表示未绑定预备布局,OpenSpec 落在 run 内——按未接入处理。
- 控制器校验结构、绑定、摘要和已有执行回执，不能仅从自报字段证明语义正确或独立执行；宿主身份/权限约束、实际执行回执与独立 Auditor 审查共同承担这一责任。不得把 `verified=true` 或工具 exit 0 当作功能通过。
- `observed_invalidations` 非空说明目标代码被 out-of-band 修改,须 revoke→invalidate 重走,不得无视继续。

完整存储不变量与门禁细节见 [留存布局](storage-layout.md#openspec-投影完整性收尾门禁);操作矩阵见 [本地运行指南](local-runtime.md#操作矩阵);阶段守卫见 [状态机](state-machine.md)。

## 5. 领域工具接线

宿主交接优先读取 `openspec/runs/<run_id>/workflow.json` 的 routing/模块索引、相关 module state 与工件引用。派发前刷新 Ledger status 校验 sequence/revision；不复制完整 Ledger、兄弟模块日志或整套领域 skill。Agent 仍能经当前快照、六件套、父级分配和实际依赖引用访问全局源码、架构与知识。快照引用失效或 routing_refresh_required 时按既有恢复动作更新，不创建第二份调度状态。

按 [领域工具受限接入](domain-tools.md) 将白名单操作映射到现有角色，不创建第二套编排游标或冻结权威。Spec-Designer 分析 UI；Implementer/Fixer 在 assignment 与写范围内精确转换资源；Test-Runner/Auditor 在当前 assignment 下取证和比较，构建仍走正式执行器。[设备与模型工具](visual-execution.md) 需要冻结的 run 环境配置、实际设备锁证明及当前 PATH 构建/基线，工具本身不验收；模型请求有总时限，缺条件沿原 Yellow 通道。Host 传认证 host-context，保留原始结果引用、转换证据和正式 Ledger payload；所有新增输出落本 run 受管目录。

prepared run 的 `ui_fidelity_required=true`、`spec_closure_required=true`（每个拆分模块一条 static PATH，位于 build 与 automation 之间），仅 applicable UI 触发对应门禁；无 UI 不制造空视觉任务。仅自动化不可用继续按 Yellow/未执行收尾，独立任务与可用构建下游不受阻。

## 命令通用约定

适用于全部 `/sdd-*` 命令，命令文件只写各自的差异。

1. 先读[四条红线](../../../AGENTS.md#四条红线)、[调用约定](../../../AGENTS.md#调用约定)和[轮询与派发](#提示采纳回报)，解析参数为绝对路径及规范 ID；协议其余部分按小节取（`reading.py show`），不整份加载。
2. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
3. 宿主把已授权身份绑定到 host-context，不能让请求内自报 role 获得权限；控制器不自动启动 Agent，不替宿主写目标代码；宿主用实际可用的任务工具启动目标角色，只传 package_root、run_root、module_id 与阅读卡路径，Ledger 按协议串行服务，定义文件不会自动安装或注册不存在的工具。payload 与命令用法见[操作矩阵](local-runtime.md#操作矩阵)。
4. 结束时输出已提交事件/当前状态/产物路径和下一动作。角色内部按授权预算运行；命令不嵌套执行其他 slash command。

参数：run-id/change-name 为 kebab-case，module-id 为 `M[0-9]{3,}`；禁止路径逃逸。JSON 中占位符、未决必填值、零必需用例不能作为有效运行输入。status 可读取尚未完成的输入状态。

硬约束：命令只解析、门控、提交/查询和派发；无业务代码、无状态双写；叶子不能私传结果；无有效批准不推断已冻结；所有门禁由对应守卫/权限校验再次验证。

输出：

```text
✅ accepted | event=<id> | run=<run-id> | next=<账本动作>
⚠️ blocked | reason=<门禁/依赖/人工> | evidence=<绝对路径或事件>
❌ failed | reason=<实际错误> | recorded=<event-id或transport-unavailable>
```

自查：参数与前置有效；工具实际存在；没有越权写入；回执来源可信；恢复指令与 phase 一致。

## 提示采纳回报

**轮询。** status --view cursor --since <sequence> 未变返回 unchanged/进度，变化返回游标、模块/信号摘要及卡大小。--view step [--module <id>] 给本步信封/预检/分配/assignment，规划加 planning_context；--view module 不带 plan/场景正文，full 仅供脚本。

**取卡。** reading.py render --root <run> (--module <id>|--global) 写 reports/reading/<card_sha256>.md，派发传路径。卡外 reading.py show --ref <文件> --section <小节>；操作矩阵支持 操作矩阵@<operation>。

**回报。** 步骤的 card_new 是上一执行实例续用原上下文时只需读的小节（红线始终在内）；宿主不回报也按执行实例计。hint{session_id,card_sha256,context_inputs} 可另报实际交付，恢复/轮换见[渐进加载](runtime.md#渐进加载)。拒绝响应及 rejected-operation.json 带 read_hint。

**机械步骤。** mechanical=true 的 accept（测试全绿）/assign（执行派发）用 `ledger.py advance --root <run> --module <id> --host-context <MO 身份>` 连续执行，逐步守卫；停在模型/人工步骤并写卡，mechanical accept 不带卡。worker 默认 `<role>-<module>`，`--worker <role>=<instance>` 可覆盖，有预检则沿用；先同会话 context-submit，被拒再交 MO。人工决定绑定游标 approval_subject_sha256（冻结/恢复/审计放行与处置）。

选择建议记 status.hint_adoption；冷恢复须满足版本/宿主回执守卫。

## 会话交接

仅替换会话时读。结束相关 worker，全局须全体 worker/审计结束。Host 创建独立会话，保存 session_rotate.checkpoint 为 checkpoint_ref。MO（模块）/Host（全局）提交 session(role,session_id,reason,checkpoint_ref)，reason=context-rotation|session-unavailable，新旧 ID 必须不同。

新 prepare 固化 host_handoff_required，替换另交 host_receipt_ref：producer=host、status=restored、run_id/module_id/role、previous_session_id/session_id、checkpoint_ref、restored_refs、evidence_refs（实际创建/恢复记录）。Ledger 核版本/恢复引用，禁换 hint 冒充。旧 Run 保留原契约。

## 本地修复单次派发

游标的 diagnose 步骤 role 为 fixer 时（轻量叶子或 `fixer_self_diagnosis`），宿主恢复游标给出的会话（通常是原 Implementer 会话）提交诊断，MO diagnosis-accept 后在同一会话继续 assign/修复，不为本地轮另起 Diagnostician 或新会话。审计期修复不适用。
