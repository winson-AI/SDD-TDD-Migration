# 宿主接入契约:如何真实走完控制流

本文件回答一个问题:**怎样才算"宿主真实执行了本控制流",而不是手写文件模拟。** 它把散落在各 reference 里的"宿主负责……"整合成逐阶段、可执行、可自证的清单。

## 命令执行

构建、自检、模拟器、预览服务等命令一律经 `skills/migration-ledger/scripts/run_command.py`：`run --log <文件> [--cwd] [--timeout] -- <argv>` 前台执行，长驻的用 `start` 启动后 `wait --log`（跟随日志末尾直到结束标记，不读日志行）。输出只进日志，交回一行 JSON：退出码、日志引用、耗时；失败时另给从日志按固定模式表（Kotlin/Java 编译器、Gradle "What went wrong"、ArkTS/hvigor、tsc、Python traceback、通用 error）grep 出的 `<日志>.failures.json`（文件/行/列/报错原文）、条数与首个定位。先看状态，失败读定位；不够再 `grep --log --pattern` 取命中行（每行截断、默认至多 50 行），不把日志整段读进上下文。正式测试经 execute_test，构建失败的定位写入结果 root_cause.failures_ref，全在写范围内直接作为 Fixer 输入。

## 宿主循环

**机械步骤。** mechanical=true 的 accept（结果已定）、assign（派发）、命令全冻结或适配器已声明的测试（以 worker 名义 submit）、报错定位全在写范围内或本模块断言失败的诊断（Ledger 写出）、确认的代码缺陷转 Fixer（diagnosis-accept）、提供方完成后的 dependency-ready/resume、外部根因或预算用尽的 audit-defer、环境缺失的 automation-unavailable、无人要求的计划评审（Ledger 写记录）、只影响上溯叶子且不挪用例的重切接受、freeze（评审/决定已记录）、complete（DoD 守卫通过）与父 module-summary 用 `ledger.py advance --root <run> --module <id> --host-context <MO 身份>` 逐步守卫提交（DoD 与汇总记录由 Ledger 写入 reports/），停在模型/人工步骤并写卡。宿主循环用 `drive.py --root <run> --host-context <MO 身份> [--wait <秒>]`：对全部模块与全局提交机械步骤，只交回每个待派（dispatch）、已派待启动或运行中（running）、宿主自交（host，带 payload）、待人工（person，带所问与决定类型）步骤与进度信号（signal：停滞、规划超时、被拒请求、待复盘，带 next_action；只在首次出现时印出，仍成立的计入 tick 的 signals_held）各一行 JSON 及一行 tick，同 Run 修订与来源变更也在其中；run 到终点多一行 done（质量、原因、报告），宿主停止并告知用户，交付由其授权；同时在做的叶子（含规划）不超过并行预算，超出的等空位，tick 计 modules_waiting；派发行带卡片路径、实例与可接续的会话（如 Fixer 接 Implementer 会话），接续时卡片只含该会话未读的小节；无可派时按 tail 方式跟随 Ledger 事件日志末尾，有新提交才返回。宿主读这些行，不读状态视图。全局的 global-plan（登记已说明覆盖时由 Ledger 起草）、audit-assign（派给已做代码审查的 Auditor）、无复测且代码审查无发现时的审计结论（取自该审查）与适配器或冻结命令驱动的波次集成派发、执行由 `ledger.advance_run` 提交，drive.py 每轮调用。worker 默认 `<role>-<module>`（`--worker <role>=<instance>` 覆盖，有预检则沿用），先同会话 context-submit，被拒交 MO。人工决定绑定游标 approval_subject_sha256。

## 总则

宿主要真实走完控制流：每步提交真实 Ledger 事件，各角色由宿主实际派发并执行。推进前按动作选 `/sdd-verify` 范围：全局基础 global，模块推进 module（本模块、祖先和实际依赖），全量投影 projection，最终交付 final；只阻断核验失败的相关范围，不把无关模块错误扩散到全部 MO。核验只证明记录与投影一致；派发、构建/设备执行和行为通过须各自的执行证据，hash 链不能证明。

## 1. 宿主必须提供、控制器不代劳的三件事

1. **身份认证与 host-context 注入**:每次 `apply`/`init` 传入认证过的 `{"role":..,"instance_id":..}`;不能让请求体自报 role，也不能让 worker 自选 host-context。
2. **真实派发 Agent**:控制器只记录 assign 并在 `status.next_steps` 给出游标；宿主用自己的 task/spawn 工具按 [Agents/*.md](../../../Agents/) 启动隔离实例，结果经 Ledger 回传；控制器不 spawn、不嵌套 slash command。
3. **真实工作落地**:Implementer/Fixer 真写 `target_root` 源码;Test-Runner 经 [execute_test.py](../../migration-ledger/scripts/execute_test.py) 调项目真实构建/测试命令;Auditor 独立实例真实重跑。`code_files`/断言由宿主真实产生，不能自填。

这三件事无法从控制器内部强制(CLI 非安全边界);它们是本契约要求宿主自证的核心。

## 2. 逐阶段接入清单

所有 op 语义见[操作矩阵](local-runtime.md#操作矩阵)。

| 命令 | 必须提交的 Ledger op(顺序) | 宿主真实工作 | 自证 |
| --- | --- | --- | --- |
| `/sdd-init` | `project_context.py prepare` → `ledger.py init`(payload 带 `project_context_ref`)→ `register`(拓扑序)→ `global-plan` | 认证 host;GO 生成功能清单/切片/覆盖;真实规范/架构/用例引用 | `status.openspec_binding.location==top-level`;`events.jsonl` 逐条增长;顶层 `openspec/runs/<run_id>/workflow.md` 出现 |
| `/sdd-plan` | scope/CASE 分配→叶子 TASK→Spec plan→MO freeze；design 按需 assign/submit/accept | SPEC 与上游用例路径、MO 技术审核及所需人工决定 | Ledger 补全 PATH/资产；CR 后更新 SPEC/已有代码；freeze 绑定当前审核 |
| `/sdd-run`、`/sdd-module` | `assign`/`context-submit`/`submit`/`accept`(implementer)→ 同序(test-runner:先 build 后 automation)→ 需要则 `diagnose`/`diagnosis-accept`/`assign(fixer)` → `complete`;父节点 `module-summary` | 派发各角色隔离实例;真写 target 代码;execute_test 跑真实命令;真实 diff/DoD 审查 | 每 assignment 有 submit+accept;`code_baseline` 与磁盘一致(否则 `observed_invalidations` 报警);`complete` 前全 PATH Green |
| `/sdd-audit` | `audit-code-review` → `audit-collect` → `audit-plan` → `audit-route-batch` → `audit-work`/`audit-retest` → `audit-verdict`(→`audit-release`) | **独立** Auditor 实例(≠ 任何 implementer/fixer/test 作者)真实重跑;Fixer 按路由修复 | `authors` 独立性校验通过;audit 报告绑定当前 snapshot;`audit-reports/<batch>.md` 生成 |
| `/sdd-archive` | 宿主 OpenSpec CLI 同步/归档(无 Ledger `archive` op) | 人工交付授权;代码合并另行授权 | `verify_openspec --scope final` 通过 + 原归档质量门禁;归档不等于合并 |
| `/sdd-status`、`/sdd-verify` | 只读,不提交事件 | —— | 核验范围适合当前动作；planning 的 projection 通过不代表 completed |

## 3. 接入自检(部署一次,证明编排器真接了 Ledger)

在一次性 throwaway workspace 上执行最小管道,确认控制器被真实调用、投影落顶层,产生的是**真实事件**而非手写文件:

```sh
python3 <pkg>/skills/migration-ledger/scripts/project_context.py prepare --root <ws>/.sdd-migration --request <req.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py init   --root <ws>/.sdd-runs/<run> --request <init.json> --host-context <host.json>
python3 <pkg>/skills/migration-ledger/scripts/ledger.py status --view full --root <ws>/.sdd-runs/<run>   # 断言 openspec_binding.location==top-level
python3 <pkg>/skills/migration-ledger/scripts/verify_openspec.py --root <ws>/.sdd-runs/<run> --scope global  # 仅断言公共记录/布局一致
```

- **管道自证**:上面四步后 `ledger/events.jsonl` 必须存在且逐条增长;编排器"跑完"却只有 registry 或散文报告,就是**没接 Ledger**。
- **派发自证**:让编排器真实执行一次 `/sdd-plan <run> <mid>`,检查新出现的 `plan` 事件 `actor` 是被派发的 spec-designer 实例、`plan_ref` 指向该 Agent 产出的工件。同理 implement 阶段检查 `code_files` 确由 Implementer 写入 `target_root`。
- **接线参照**:[simulate_storage.py](../../migration-ledger/tests/simulate_storage.py) 调用真实 prepare/Ledger/执行器，可作为接线对照；其中审批、角色和业务输入是测试夹具，不证明真实授权、派发或设备验证。

## 4. 判定与红线

- `status.openspec_binding.location==in-run-fallback` 表示未绑定预备布局,OpenSpec 落在 run 内——按未接入处理。
- 控制器校验结构、绑定、摘要和已有执行回执，不能仅从自报字段证明语义正确或独立执行。不得把 `verified=true` 或工具 exit 0 当作功能通过。
- `observed_invalidations` 非空说明目标代码被 out-of-band 修改,须 revoke→invalidate 重走,不得无视继续。

完整存储不变量与门禁细节见 [留存布局](storage-layout.md#openspec-投影完整性收尾门禁);操作矩阵见 [本地运行指南](local-runtime.md#操作矩阵);阶段守卫见 [状态机](state-machine.md)。

## 5. 领域工具接线

宿主交接优先读取 `openspec/runs/<run_id>/workflow.json` 的 routing/模块索引、相关 module state 与工件引用。派发前刷新 Ledger status 校验 sequence/revision；不复制完整 Ledger、兄弟模块日志或整套领域 skill。Agent 仍能经当前快照、六件套、父级分配和实际依赖引用访问全局源码、架构与知识。快照引用失效或 routing_refresh_required 时按既有恢复动作更新，不创建第二份调度状态。

按 [领域工具受限接入](domain-tools.md) 把白名单操作映射到现有角色，不另建游标或冻结权威：Spec-Designer 捕获与分析 UI；Implementer/Fixer 在 assignment 与写范围内转换资源；Test-Runner/Auditor 在当前 assignment 下取证比较，构建走正式执行器。宿主还要配置 `legacy_preview`（设备 serial / 模拟器 / 虚拟机 + APK 或构建命令、浏览器 url、或 none 与原因），保证 adb 或 Playwright 可用，agent 导航另配 navigator；legacy-capture 与 Android / web 目标的 visual-* 需 host-context 带 device_lock（serial 或 url）；web 目标由宿主部署并在页面声明构建哈希。[设备与模型工具](visual-execution.md) 需冻结的 run 环境配置、设备锁证明及当前 PATH 构建/基线，工具本身不验收；模型请求有总时限，缺条件走 Yellow。Host 传认证 host-context，保留原始结果引用与转换证据；新增输出落本 run 受管目录。

## 调用约定

Agent Markdown 使用 `name/description/mode: subagent`，命令只有 `description`，技能用 `name/description`；宿主可按实际注册格式转换，不把 `mode` 当作所有产品的原生字段。命令解析请求后由宿主提交 Ledger；编排角色提交 assign（审计为 audit-assign / audit-test-assign），Ledger 接受后宿主用实际提供的任务工具（`task`，或读取定义后 spawn_agent 启动隔离实例）派发；不嵌套 slash command，不能只写一段工具调用文本便宣布已派发。Ledger 的 transport ACK 是唯一传输回执，不携带业务决策。迁移运行允许并行无冲突模块，数量受输入与宿主限制。

## 专题索引

宿主与编排角色定位专题用；被派发的角色从阅读卡的按需清单取小节。每节均为该专题的唯一权威表述。

| 专题 | 触发 | 权威小节 |
| --- | --- | --- |
| 本地控制器、恢复 | 运行控制器；恢复会话 | [runtime.md#总则](runtime.md#总则)、[local-runtime.md#操作矩阵](local-runtime.md#操作矩阵) |
| 项目上下文 | prepare / 更新项目配置 | [project-context.md#总则](project-context.md#总则) |
| 父子 MO、轻量叶子、批量冻结 | GO 切片、父 MO 拆分、子 MO 规划 | [module-decomposition.md#总则](module-decomposition.md#总则) |
| 二方库、目标已有能力、fidelity、provider 归属 | 范围含复用或目标已有实现 | [reuse-dependencies.md#总则](reuse-dependencies.md#总则) |
| 同 run 追加来源 | 新增只读来源 | [source-changes.md#总则](source-changes.md#总则) |
| 阶段上下文就绪 | 每次派发前 | [context-readiness.md#总则](context-readiness.md#总则) |
| 功能清单完备性 | GO 切片 | [slicing.md#总则](../../migration-global/references/slicing.md#总则) |
| 构建 / 单测 / 静态 / 自动化缺测 | Test-Runner 派发 | [build-automation.md#总则](build-automation.md#总则) |
| Auditor 范围与代码治理 | 审计各环节 | [audit-scope.md#总则](audit-scope.md#总则)、[audit-code-review.md#顺序与职责](audit-code-review.md#顺序与职责) |
| 父 MO 命名、收尾报告 | GO 收尾 | [migration-report.md#总则](migration-report.md#总则) |
| 四维切片、语义模型、领域工具、资源与参数搬运 | 规划与实现 | [dimension-slicing.md#总则](dimension-slicing.md#总则)、[semantic-extraction.md#总则](semantic-extraction.md#总则)、[domain-tools.md#总则](domain-tools.md#总则)、[resource-transfer.md#总则](resource-transfer.md#总则) |
| 阻塞感知、watchdog | 门禁拒绝、worker 超时 | [progress-recovery.md#总则](progress-recovery.md#总则)、[watchdog.md#总则](watchdog.md#总则) |
| 埋点 | 认领范围含埋点事件 | [telemetry.md#总则](telemetry.md#总则) |
| 资产根与留存 | 任何读写工件 | [storage-layout.md#总则](storage-layout.md#总则) |
| 宿主接入、核验范围、模型档位 | 宿主编排 | [host-integration.md#总则](host-integration.md#总则)、[model-routing.md#总则](model-routing.md#总则) |

## 命令通用约定

适用于全部 `/sdd-*` 命令，命令文件只写各自的差异。

1. 先读[四条红线](../../../AGENTS.md#四条红线)、[调用约定](#调用约定)和[轮询与派发](#提示采纳回报)，解析参数为绝对路径及规范 ID；协议其余部分按小节取（`reading.py show`），不整份加载。
2. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影；宿主自己的运行记录放 staging/host，不登 issue。
3. 宿主把已授权身份绑定到 host-context，请求内自报 role 不获权限；派发按[宿主派发](runtime.md#宿主派发)，定义文件不会自动安装或注册不存在的工具；payload 与用法见[操作矩阵](local-runtime.md#操作矩阵)。无冲突模块的 MO 审核（plan-review、freeze、decompose-accept）由宿主并行派发独立实例，并行数受输入与宿主限制。
4. 结束时输出已提交事件/当前状态/产物路径和下一动作。角色内部按授权预算运行。

参数：ID 格式与路径规则见[运行协议](runtime.md#路径与加载)；JSON 中占位符、未决必填值、零必需用例不能作为有效运行输入。status 可读取尚未完成的输入状态。

硬约束：命令只解析、门控、提交/查询和派发；无业务代码、无状态双写；叶子不能私传结果；无有效批准不推断已冻结；所有门禁由对应守卫/权限校验再次验证。

输出：

```text
✅ accepted | event=<id> | run=<run-id> | next=<账本动作>
⚠️ blocked | reason=<门禁/依赖/人工> | evidence=<绝对路径或事件>
❌ failed | reason=<实际错误> | recorded=<event-id或transport-unavailable>
```

自查：参数与前置有效；工具实际存在；没有越权写入；回执来源可信；恢复指令与 phase 一致。

## 提示采纳回报

**轮询。** status --view cursor --since <sequence> 未变返回 unchanged，变化返回游标、信号摘要及卡大小；--view step [--module <id>] 给本步信封/预检/分配/assignment（规划加 planning_context）；--view module 不带 plan 正文，full 仅供脚本。

**取卡。** render/show 取卡与单节（--template <名>、操作矩阵@<operation>），slicing_skill 随卡写入，human_required=false 不征求人工。卡只给本步要用的：模板限本步所写工件，专题小节按触发列入 read_when_writing（执行角色仅在计划取用 provider 时列复用），Test-Runner 构建与自动化共读角色文本，等依赖的步骤不带卡。

**回报。** card_new 是续用原上下文的执行实例只需读的小节（含红线），宿主不回报也按执行实例计。hint{session_id,card_sha256,context_inputs} 可另报实际交付（不全则忽略，不拒操作），恢复/轮换见[渐进加载](runtime.md#渐进加载)，拒绝响应带 read_hint。

选择建议记 status.hint_adoption；冷恢复须满足版本/宿主回执守卫。

## 会话交接

仅替换会话时读。结束相关 worker，全局须全体 worker/审计结束。Host 创建独立会话，保存 session_rotate.checkpoint 为 checkpoint_ref。MO（模块）/Host（全局）提交 session(role,session_id,reason,checkpoint_ref)，reason=context-rotation|session-unavailable，新旧 ID 必须不同。

新 prepare 固化 host_handoff_required，替换另交 host_receipt_ref：producer=host、status=restored、run_id/module_id/role、previous_session_id/session_id、checkpoint_ref、restored_refs、evidence_refs（实际创建/恢复记录）。Ledger 核版本/恢复引用，禁换 hint 冒充。

## 本地修复单次派发

游标的 diagnose 步骤 role 为 fixer 时（轻量叶子或 `fixer_self_diagnosis`），宿主恢复游标给出的会话（通常是原 Implementer 会话）提交诊断，MO diagnosis-accept 后在同一会话继续 assign/修复，不为本地轮另起 Diagnostician 或新会话。审计期修复不适用。
