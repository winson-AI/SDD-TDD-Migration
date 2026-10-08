# GO → 父 MO → 子 MO：范围、上下文与规划契约

## 总则

project 指完整项目及其功能树；single-module 只选择一个根功能。GO 划模块 scope/上下文，MO 按原子性决定细分或进入叶子 tasks 规划；不为凑层级创建同范围孩子。父子均读全局代码/架构/知识，权限限定于认领 scope；规划绑定 Ledger 的 planning_context 和 module_inputs。实际父节点只管理/汇总，叶子持有 SPEC、代码、测试与验收；父聚合失败不回写兄弟。全部叶子本轮结束且父 MO 汇总有效后，GO 才统一启动 Auditor。

轻量叶子：GO 可直接登记 `lean_leaf`；MO 也可在拆分提案中确认当前根为原子叶子，经 GO 接受后保留节点进入 SPEC 规划。原子性不替代测试设计与冻结；有代码问题才进入 Fixer，其本地轮可在原 Implementer 会话先诊断后修复，MO 接受诊断，审计期恢复独立 Diagnostician。运行级 `fixer_self_diagnosis` 可用于所有模块（默认关闭）。多个孩子的具体批准可汇总一次提交，见[批量冻结](#父级批量冻结信封)。

## 1. 三层职责

| 层级 | 认领的范围 | 规划输出 | 迁移管理职责 |
| --- | --- | --- | --- |
| GO | 本轮项目范围或指定根功能；全局视角 | global_spec、根模块 ID、scope、需求/CASE 映射、代码范围、依赖及上下文 | 全局 registry、DAG、资源锁、父 MO 调度、跨模块升级、统一 Auditor |
| 父 MO | GO 分配的一个模块及其 scope | 在该范围内划分子模块，为每个子 MO 分配 scope、用例、写范围、依赖和完成子模块所需的上下文 | 看护整个认领模块，防止遗漏与重复，跟踪子 MO、管理依赖、等待并汇总 |
| 子 MO | 父 MO 分配的子功能及 scope/context | 拆 tasks，组织 Spec Designer / Test Runner 完成六件套、测试路径及追溯 | 独立冻结、Coding → Testing → 预算内收敛 → DoD 或挂起 |

拆分按需推进 **GO 模块 → MO 子模块 → 叶子 tasks**；原子根可直接成为叶子。子 MO 不再建下一层 MO；粒度或边界冲突经 `realloc-request` 报父，由父 `redecompose` 或 GO 协调。编码前调整后重规划、校验、冻结；编码后契约变化走 CR。业务语义变化交人工，不私改分配。

两种入口只决定宿主范围，均允许 GO/MO 确认原子叶子。用户无需额外输入模块 ID、scope、SPEC 或 Testing list。

根功能与子功能是同一 MO 角色的不同职责实例。父节点存入 `module_groups`，执行子节点存入 `modules`，ID 全局唯一；父 MO 不重复编码或重复验收孩子的 CASE。

## 2. 全局可见，按分配范围执行

每次规划、拆分、变更前，父 MO 和子 MO 都必须读取步骤视图（`status --view step`）给出的 `planning_context`：

| 内容 | 用途 |
| --- | --- |
| `legacy_root` / `target_root` | 全局存量/目标代码：生产入口、公共能力、已迁移实现 |
| `global_spec` / `new_architecture` | 全局业务、架构与接口约束 |
| `project_context_ref` / `project_sources` | 本轮固定的规范、用例、规则及 `knowledge_paths` 知识资料 |
| `modules` | 当前执行节点的父级、scope、context_refs、CASE、写范围、依赖 |
| `parents` | 父子关系及汇总责任 |

再读取同一视图的 `module_input` 作为本 MO 的权威分配包：`module_id`、`parent_module_id`、`scope`、`case_ids`、`write_paths`、`dependencies`、`context_refs`；子包另带 `parent_context`，保留父模块 ID/scope/context_refs。父 MO 认领 GO 的包，子 MO 认领父 MO 经 GO 接受的包。认领由宿主将实例绑定到模块；拆分提案与 plan 不抄写分配包或全局上下文，Ledger 接受时绑定两者当前内容的摘要，不新增一个虚假的 claim 操作。

上下文逐层细化：GO 的 context_refs 指向入口、相关代码、架构约束、知识、接口/复用 owner 及需求/用例映射；父 MO 为每个子功能提供聚焦文档绝对 path/sha256。子 MO 综合全局/父/子上下文拆 tasks，标明需求、PATH 与复用关系。共享上下文可引同一工件，不截断全局读取。

局部 context pack 用于聚焦；全局可读不扩大 scope 或写权限。先检查目标已有实现和兄弟分工，明确“复用什么、谁实现、谁消费、写哪些文件、不实现哪些行为”。共同 CASE/全局需求 ID 可覆盖不同子职责，但须说明参与方式和唯一实现 owner；共享写路径依旧受锁约束，重叠业务分工必须审核。

`planning_context` 仅含职责结构，不含兄弟变化中的 phase/revision；实时进度、锁和修复 memory 另读 Ledger。拆分/冻结/派发核对绑定摘要与当前上下文及分配，过期拒绝；上游评审限定影响，未变冻结模块保留 execution_context_ref；重拆仅等待受影响 worker。源码验 baseline。

## 3. 分配与登记门禁

行为契约是必选门禁（prepare 固化）：register/decompose 提交根/子 behavior_review（见模板），覆盖所附分配，不抄写 scope 摘要与用例列表；证据完整、unresolved=[]。共享需 owner、消费者与集成责任；global-plan 解析唯一叶子 owner，边界疑问交父级/GO/人工。

子 MO 的 source_closure 即其行为审阅，以 scenario_trace 覆盖任务。共享能力与复用目录使用同一 capability_id 时，目录的 provider owner 必须是行为审阅解析出的叶子 owner。子功能可验收，任务可单层；基础能力需消费者。

原子根功能可由 GO 登记为 `lean_leaf=true` 执行叶子（跳过拆分与汇总），附 `leaf_review_ref`；其余根功能由 GO `register` 设 `decomposition_required=true`，提交非空 `scope.in`、显式 `scope.out`、非空 `requirement_ids` 与 `context_refs`。CASE/需求须来自本轮输入，写范围包含于 target_root。导入方案由 GO 补全转为此格式。

MO 确认原子根时，`decompose.plan_ref` 的文档仅含 `kind: atomic-leaf`、`parent_module_id`、`rationale`、`leaf_review_ref`。审阅说明职责完整、唯一 writer、依赖可控及独立验证路径；现有四维/行为/验证边界门禁仍适用。GO `decompose-accept` 核对当前绑定与证据，保留 ID/scope/CASE/依赖，清待拆分标记，进入未冻结 SPEC 规划。不允许夹带 children 或范围变化；已编码节点不能用此入口绕过 CR，已拆父组调整走 redecompose。

| 操作 | 角色 / 请求 scope | 输入与门禁 |
| --- | --- | --- |
| `decompose` | MO / 当前根 ID | `plan_ref` 为拆分方案或原子叶子结论；decomposition 预检随操作登记 |
| `decompose-accept` | GO / 当前根 ID | `review_ref`；提案绑定仍有效；拆分则移父节点至 module_groups 并登记孩子，原子结论则原节点进入叶子规划 |
| `realloc-request` | MO / 子或根 ID | `reason` + `evidence_refs`；切片/边界冲突提单，保存恢复阶段后进入 `waiting-upstream`；无父或父级上溯交 GO run-review |
| `redecompose` | 父 MO / 父 ID | `plan_ref`；重组方案重新划分 children 并覆盖父范围 |
| `redecompose-accept` | GO / 父 ID | `review_ref`；复核方案，比较范围、上下文、四维/行为审阅与依赖；保留未变孩子 Green 并恢复请求前阶段，受影响孩子及依赖闭包重新规划、保留 blocker/失败/预算，已实施下线模块转入 superseded_modules |
| `module-summary` | 父 MO / 父 ID | `summary_ref` + 当前父 next_step.payload 中的 subject_sha256；全部孩子本轮已收尾 |

使用 [拆分模板](../../../template/module-decomposition.json)。每个孩子提供稳定 ID、功能 name、scope、context_refs、case_ids、绝对 write_paths、dependencies。要求：

1. 子需求/CASE 属于父范围；所有孩子的需求并集、CASE 并集各自完整覆盖父范围。子 scope.out 保留父排除项，可新增排除项；scope.in 描述真实子职责，语义不能扩张。
2. 子写范围包含于父范围；ID 全局唯一。孩子不得设置 decomposition_required 或自行指定 parent_module_id；GO 接受时写入父 ID。
3. 内部依赖引用本次孩子；外部依赖限父节点已批准依赖，图无环。孩子只认领实际消费的依赖，不继承父依赖并集；父 provider 细化时，consumer_dependencies 明确消费者实际等待的孩子，并提交 consumer_verifications。
4. 有 blocker、活动 worker、已冻结或已生成代码的父节点不能直接拆分；不能通过删除/拆分规避失败历史。
5. global-plan 可先验完整根/叶子 registry 的需求、CASE、功能、归属与依赖；待拆根保留覆盖责任但不能编码。已就绪叶子只检查自身、祖先及实际依赖，无关根继续细分。接受拆分后 GO 重验当前 registry，需求 owner 与 scope 一致；保留未变 SPEC/测试设计/执行上下文，影响闭包重规划。原子确认未改 registry，无需重复全局覆盖审查。
6. 子 plan 绑定的分配必须仍是当前分配；每个 task 的 global_requirement_ids（无别名时使用 requirement_ids）限定在该子模块内，并覆盖其全部获分配需求；测试路径不得加入未分配 CASE。原有需求→task→PATH 追溯继续有效。
7. 拆分与认领不等于 SPEC 冻结批准。子 MO 组织六件套、测试设计和澄清，按[控制主线](state-machine.md#控制主线)审核冻结后才授权编码。

## 4. 独立执行、父看护与统一审计

每个子 MO 独立 Coding → Testing → 可修复 Red/Yellow 在本模块配置预算内 Fixer → 正式复测 → DoD 或明确挂起。一个孩子失败不取消兄弟；父/全局聚合 Red 不回写孩子。真实依赖变化仅影响确认的消费者。

父 MO 持续读取子模块 SPEC、tasks、用例覆盖、基线、根因与修复 memory，确认认领范围无遗漏/重复/扩张。等所有孩子完成或明确挂起；module-summary 记录逐子结论、范围覆盖、遗留问题和审计移交，不代验收子 CASE。

Ledger 的 subject_sha256 绑定当前拆分引用和孩子 revision；孩子状态/证据变化后，旧父汇总失效，须重新核验。父 Green 要求全部孩子当前 DoD Green 且汇总有效，不替代 Auditor。

GO 等全部子 MO 收尾且父汇总有效后启动 Auditor。status.module_rounds 区分 leaf/parent modules。收集问题子模块，不把父聚合 Red 记成失败 CASE。Auditor 读取对应 SPEC/测试路径并委派修复复测，裁决只归 Auditor。最终审计要求全子模块 Green、遗留清空且父汇总有效。

## 5. 宿主与兼容

本地控制器维护事件、分配范围、引用、摘要和门禁；宿主负责实际创建/恢复父子 MO、实例与模块绑定、传递 Ledger 引用和执行写隔离。投影不表示 Agent 已启动。

## 6. 二方库作为逐层规划依据

GO 切片前建立 TARGET/外部来源的功能语义目录，结合需求分配 scope 与提供方/消费者；父 MO 映射认领模块需求并划分共享适配 owner，将适用能力及差异传给子 MO。子 MO 在 scope 内拆接入、适配和缺口 tasks，以 reuse_plan_ref 绑定到正式 plan。双方仍可读取全局 reuse_sources；外部路径不进入 write_paths。能力映射不替代用户需求与验收，具体见 [复用协议](reuse-dependencies.md#3-按三层编排提取与细化)。

## 7. 拆分与任务规划的上下文验收

父 decompose 随交 decomposition 预检，叶子 plan 随交 planning 预检；接受/冻结验同版报告，全球源码/架构/知识/分工不能被局部 context pack 遮蔽。见 [上下文就绪](context-readiness.md#2-精确插入节点)。

## 父 MO 统一命名

父 MO 的名称固定为 `parent-mo-<module_id>`，模块 ID 保留原来的大写 M 与编号，例如 M010 → parent-mo-M010。GO 登记根模块后即使用该名称，拆分为 module_groups 后保持不变；跨会话冷恢复仍使用同一名称。

- 父 MO 的 next_steps 条目包含 agent_name（full 视图另有 `parent_mo_names` 汇总），GO 接受拆分等其他角色动作不冒用父名称。
- 宿主创建/恢复父 MO 时，将该名称用于支持的 name/title/可见标签。若工具限制技术 ID 字符集，技术 ID 保持合法，展示标签与 Ledger agent_name 仍使用上述格式。
- `session` 的 role 仍为 module-orchestrator；父 session 未提供 agent_name 时自动补全，提供不同名称则拒绝。instance_id、session_id 是宿主真实身份，不以名称替代认证或授权。
- 名称是运行展示元数据，不属于分配包或 planning_context。

## 四维父子覆盖

父 MO 认领并读取模块实现/四维分析等上下文，先划子模块 scope，再按 [四维协议](dimension-slicing.md#4-控制节点与交接) 生成子 dimension_analysis_ref（绑定 parent_ref/parent_item_ids）和 dimension_partition_review_ref；GO 两次审查 proposal/accept，拒绝遗漏父项或重复子 item ID。scope、CASE、写锁与共享提供方 owner 原规则继续有效。

## 父级批量冻结信封

父 MO 拆分出多个孩子时，可以把各孩子的 decision_envelope（scope、acceptance、allowed_alternatives、forbidden_changes）汇成一份 [批量信封](../../../template/batch-envelope.json)，交人类一次批准（decision `kind=batch-envelope`，module_id 为父）。子 plan 的 envelope 与信封条目完全一致时，子 MO 审阅详细 tasks/PATH 后附 review_ref 即可 freeze，不再逐个等待人类；任一孩子超出条目（扩大范围、替换提供方、改变用户可见语义等）仍须自己的人类批准。信封批准不替代 MO 的计划审阅，也不改变冻结后的 CR 规则。

## 验证边界

behavior_review.verification 必填，字段见[模板](../../../template/module-decomposition.json)。provider_inputs 精确匹配实际 dependencies，逐项绑定 contract_ref 和 required_stage（implemented/verified）。同触发必须有不同的独立观察，否则重切；隔离策略和固定输入/替身契约由 GO/父 MO 以源码证据审阅。唯一 ID、独立作者或独立颜色不能替代行为独立性。

拆分文档写 case_acceptance：父模块验收的每条 CASE 对应唯一验收它的子模块（记为其 acceptance_case_ids），其余持有该 CASE 的是贡献方；不验收任何 CASE 的子模块在 supporting_slices 写明为何不能并入使用它的切片。依赖链达 3 个切片或过半切片须等另一切片验证完成时，independence_review（rationale、evidence_refs）说明为何不能按业务行为切。根模块以 acceptance_case_ids 声明（缺省为全部），一条 CASE 只由一个根验收。

叶子 source_closure 保持分配的 verification；行为 PATH 引用其 fixture_contract_ref。implemented provider 可解除编码准备依赖，正式测试/DoD 仍需 provider 验证完成。共享 provider 只一个实现 owner；消费者负责明确集成 CASE。结构门禁校验归属、引用、完整性，语义独立性由规划审核和最终 Auditor 复核。

## 最小验收切片

叶子 MO 按独立业务结果/验证闭包切片，是冻结、测试及 DoD 单位。TASK 分批实现、全部接受后才测试；冻结前只设计。互不依赖的大叶子回父 MO 重切，不新增 TASK 状态机。Auditor 统一审计，可同 Run 多轮整改复审。
