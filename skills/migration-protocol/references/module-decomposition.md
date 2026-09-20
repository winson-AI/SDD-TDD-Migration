# GO → 父 MO → 子 MO：范围、上下文与规划契约

## 1. 三层职责

| 层级 | 认领的范围 | 规划输出 | 迁移管理职责 |
| --- | --- | --- | --- |
| GO | 本轮项目范围，或用户指定的一个根功能；保留全局视角 | 根模块 ID、scope、Testing list、SPEC 草稿、代码范围、依赖及完成模块所需的上下文 | 全局 registry、DAG、资源锁、父 MO 调度、跨模块升级、统一 Auditor |
| 父 MO | GO 分配的一个模块及其 scope | 在该范围内划分子模块，为每个子 MO 分配 scope、用例、写范围、依赖和完成子模块所需的上下文 | 看护整个认领模块，防止遗漏与重复，跟踪子 MO、管理依赖、等待并汇总 |
| 子 MO | 父 MO 分配的一个具体子功能及其 scope/context | 将子功能拆为可执行 tasks，组织 Spec Designer / Test Runner 完成正式六件套、测试路径和追溯 | 独立冻结、Coding → Testing → 一轮 Fixer → 复测 → DoD 或明确挂起 |

拆分方向固定为 **GO 拆模块 → 父 MO 拆子模块 → 子 MO 拆 tasks**。子 MO 不再创建下一层 MO；发现粒度或边界不合适，通过 Ledger 向父 MO 提交调整请求，父 MO 核对模块范围，涉及根模块边界由 GO 协调，跨模块或不确定业务边界交人工决策。运行中调整仍须遵守 CR、重新冻结和证据失效规则，不能自行改分配包。

`project` 直接指定完整项目，GO 识别其中各根功能及其子功能。`single-module` 只指定其中一个根功能，其父 MO 仍须拆分子功能。用户无需额外输入模块 ID、scope、SPEC 或 Testing list。原子根功能可产生一个有明确职责的执行孩子，不虚构多个业务功能。

根功能与子功能是同一 MO 角色的不同职责实例。父节点存入 `module_groups`，执行子节点存入 `modules`，ID 全局唯一；父 MO 不重复编码或重复验收孩子的 CASE。

## 2. 全局可见，按分配范围执行

每次规划、拆分、变更前，父 MO 和子 MO 都必须读取 `status.planning_context`：

| 内容 | 用途 |
| --- | --- |
| `legacy_root` / `target_root` | 全局存量/目标代码：生产入口、公共能力、已迁移实现 |
| `global_spec` / `new_architecture` | 全局业务、架构与接口约束 |
| `project_context_ref` / `project_sources` | 本轮固定的规范、用例、规则及 `knowledge_paths` 知识资料 |
| `modules` | 当前执行节点的父级、scope、context_refs、CASE、写范围、依赖 |
| `parents` | 父子关系及汇总责任 |

再读取 `status.module_inputs[module_id]` 作为本 MO 的权威分配包：`module_id`、`parent_module_id`、`scope`、`case_ids`、`write_paths`、`dependencies`、`context_refs`；子包另带 `parent_context`，保留父模块 ID/scope/context_refs。父 MO 认领 GO 的包，子 MO 认领父 MO 经 GO 接受的包。认领由宿主将实例绑定到模块，规划提交复制完整包到 `assigned_module` 表示核对接受；该字段不替代宿主身份鉴别，也不新增一个虚假的 claim 操作。

上下文逐层细化：GO 的 `context_refs` 指向完成模块所需的入口、相关代码位置、架构约束、知识、接口/复用 owner、SPEC 草稿及 Testing list；父 MO 为每个子功能提供相应聚焦文档的绝对 path/sha256。子 MO 同时读取全局、父级、子级上下文，拆 tasks 时标明需求、PATH、生产链路和复用关系。共享上下文可引用同一不可变工件，不能只传一句摘要或截断全局读取能力。

局部 context pack 用于聚焦；全局可读不扩大 scope 或写权限。先检查目标已有实现和兄弟分工，明确“复用什么、谁实现、谁消费、写哪些文件、不实现哪些行为”。共同 CASE/全局需求 ID 可覆盖不同子职责，但须说明参与方式和唯一实现 owner；共享写路径依旧受锁约束，重叠业务分工必须审核。

`planning_context` 只绑定职责结构，不含兄弟正在变化的 phase/revision；实时进度、锁和修复 memory 另读 Ledger。`assigned_module` 绑定本模块分配及父上下文。父拆分提交、GO 接受及子 plan/freeze/dispatch 均核验相应分配/引用，拒绝过期或自行改写的包。全局源码阅读与 scope.in 的语义包含关系仍由 Agent/宿主审核；结构检查不能证明已阅读或完全理解代码。源码变化沿用 baseline 检测。

## 3. 分配与登记门禁

新入口由 GO `register` 根功能，设置 `decomposition_required=true`，同时提交非空 `scope.in`、显式 `scope.out`（可为空）、非空 `scope.requirement_ids` 和非空 `context_refs`。其中 requirement_ids 使用全局需求 ID。根模块的 CASE/需求须来自本轮输入，写范围包含于 target_root。人工导入方案先由 GO 分析补全并转成此分配格式；这些字段不增加用户入口负担。

| 操作 | 角色 / 请求 scope | 输入与门禁 |
| --- | --- | --- |
| `decompose` | 父 MO / 父 ID | `plan_ref` 指向拆分方案：parent_module_id、rationale、完整 planning_context、assigned_module、children |
| `decompose-accept` | GO / 父 ID | `review_ref`；已有 MO 提案，复查当前范围、覆盖、上下文和依赖；原子移动父节点至 module_groups 并登记孩子 |
| `module-summary` | 父 MO / 父 ID | `summary_ref` + 当前父 next_step.payload 中的 subject_sha256；全部孩子本轮已收尾 |

使用 [拆分模板](../../../template/module-decomposition.json)。每个孩子提供稳定 ID、功能 name、scope、context_refs、case_ids、绝对 write_paths、dependencies。要求：

1. 子需求/CASE 属于父范围；所有孩子的需求并集、CASE 并集各自完整覆盖父范围。子 scope.out 保留父排除项，可新增排除项；scope.in 描述真实子职责，语义不能扩张。
2. 子写范围包含于父范围；ID 全局唯一。孩子不得设置 decomposition_required 或自行指定 parent_module_id；GO 接受时写入父 ID。
3. 内部依赖引用本次孩子；外部依赖限父节点已批准依赖，图无环。孩子继承父依赖；依赖父功能的消费者改为等待其全部孩子。
4. 有 blocker、活动 worker、已冻结或已生成代码的父节点不能直接拆分；不能通过删除/拆分规避失败历史。
5. 接受拆分后原 global-plan 失效；GO 重新检查全部子模块覆盖与边界；global-plan 中需求 owner 须与已分配子范围一致，接受后才可派发实现。根功能待拆分时禁止直接进入正式子 plan/global-plan/编码。
6. 子 plan 的 `assigned_module` 必须匹配当前分配；每个 task 的 global_requirement_ids（无别名时使用 requirement_ids）限定在该子模块内，并覆盖其全部获分配需求；测试路径不得加入未分配 CASE。原有需求→task→PATH 追溯继续有效。
7. 拆分与认领不等于 SPEC 冻结批准。子 MO 组织正式六件套、测试设计、plan 澄清和人工冻结后才授权编码。

## 4. 独立执行、父看护与统一审计

每个子 MO 独立 Coding → Testing → 可修复 Red/Yellow 自动一轮 Fixer → 正式复测 → DoD 或明确挂起。一个孩子失败不取消兄弟；父/全局聚合 Red 不回写孩子。真实依赖变化仅影响确认的消费者。

父 MO 持续读取子模块 SPEC、tasks、用例/PATH 覆盖、代码基线、结果/根因、修复 memory 与恢复点，确认整个认领模块未漏项、未重复实施、范围未扩张。父 MO 等所有孩子本轮完成或基于自身证据明确挂起；排队、未派发、单个 worker 退出不算收尾，有可推进动作则继续。`module-summary` 记录逐子结论、范围覆盖、遗留问题和审计移交，不制造父级测试结果、不代验收子 CASE。

Ledger 的 subject_sha256 绑定当前拆分引用和孩子 revision；孩子状态/证据变化后，旧父汇总失效，须重新核验。父 Green 要求全部孩子当前 DoD Green 且汇总有效，不替代 Auditor。

GO 等全部子 MO 收尾和全部父汇总有效后统一启动 Auditor。`status.module_rounds` 区分 leaf_modules / parent_modules，registered_modules 包含两者。收集实际问题子模块，不把父聚合 Red 重复记成失败 CASE。Auditor 读取对应 SPEC/测试路径，委派 Fixer 和 Testing；审计裁决只归 Auditor。补丁导致父汇总过期时重新汇总；最终独立审计仍要求全部子模块 Green、遗留队列清空及父汇总有效。

## 5. 宿主与兼容

本地控制器维护事件、分配范围、引用、摘要和门禁；宿主负责实际创建/恢复父子 MO、实例与模块绑定、加载 Used Skills、传递 Ledger 引用和执行写隔离。投影不表示 Agent 已启动。

旧扁平 run 不自动转树；没有 decomposition_required 的旧叶子保留兼容，不静默改写历史。旧递归树可读取和汇总，新拆分禁止子 MO 再创建 MO。新的 project/single-module 入口都遵循本文三层定义。CLI operation schema 仍为 1；宿主使用当前 schema 与模板。边界调整没有旁路操作，超出既有控制器能力时记录并请求处理，不能假装已完成重分配。

## 6. 二方库作为逐层规划依据

GO 切片前建立 TARGET/外部来源的功能语义目录，结合需求分配 scope 与提供方/消费者；父 MO 映射认领模块需求并划分共享适配 owner，将适用能力及差异传给子 MO。子 MO 在 scope 内拆接入、适配和缺口 tasks，以 reuse_plan_ref 绑定到正式 plan。双方仍可读取全局 reuse_sources；外部路径不进入 write_paths。能力映射不替代用户需求与验收，具体见 [复用协议](reuse-dependencies.md)。

## 7. 拆分与任务规划的上下文验收

父 MO 在 decompose 前提交 decomposition 报告，GO 在 decompose-accept 核对同一依据；子 Spec Designer 在 plan 前提交 planning 报告，由子 MO freeze 再验。不可只传目录或摘要，须包含权威输入、生产链路、接口 owner 和可执行任务依据。详见 [上下文就绪协议](context-readiness.md)。

## 父 MO 统一命名

父 MO 的名称固定为 `parent-mo-<module_id>`，模块 ID 保留原来的大写 M 与编号，例如 M010 → parent-mo-M010。GO 登记根模块后即使用该名称，拆分为 module_groups 后保持不变；跨会话冷恢复仍使用同一名称。project 的各父 MO 分别命名；single-module 的唯一根父 MO 同样遵守。不同 run 以 run_id 区分，不修改该名称格式。

- Ledger `status.parent_mo_names` 返回父 ID → 名称；父 MO 的 next_steps 条目包含 agent_name，GO 接受拆分等其他角色动作不冒用父名称。
- 宿主创建/恢复父 MO 时，将该名称用于支持的 name/title/可见标签。若工具限制技术 ID 字符集，技术 ID 保持合法，展示标签与 Ledger agent_name 仍使用上述格式。
- `session` 的 role 仍为 module-orchestrator；父 session 未提供 agent_name 时自动补全，提供不同名称则拒绝。instance_id、session_id 是宿主真实身份，不以名称替代认证或授权。
- 名称是运行展示元数据，不加入冻结 assigned_module/planning_context，旧 run 的 SPEC/分配摘要不因命名增强失效；无需改写旧事件。

## 四维父子覆盖

父 MO 认领并读取模块实现/四维分析等上下文，先划子模块 scope，再按 [四维协议](dimension-slicing.md) 生成子 dimension_analysis_ref（绑定 parent_ref/parent_item_ids）和 dimension_partition_review_ref；GO 两次审查 proposal/accept，拒绝遗漏父项或重复子 item ID。scope、CASE、写锁与共享提供方 owner 原规则继续有效。
