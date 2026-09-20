# SDD-TDD-Migration

按功能切片迁移的 Agent 工作流包：9 个执行/治理角色 + 1 个 Ledger。输入整体规范、新架构、存量代码路径、目标代码路径及整体测试用例，先拆分模块和用例，再并行迁移，最后独立审计。

## 从这里开始

1. 读取 [AGENTS.md](AGENTS.md)，按角色索引渐进加载。
2. 首次提供项目资料，宿主根据 [project-context.json](template/project-context.json) 保存到工作目录 `.sdd-migration/project-context.json`；后续自动读取，用户明确更新时增量保存。无需每次重填运行输入。
3. 在支持此包的宿主中执行 `/sdd-init`，先固定项目配置和本次请求快照，再由 Global 生成 [运行输入](template/global-input.json)、SPEC/Testing list、账本和模块规划；`/sdd-plan <run-id> <module-id>` 完成正式六件套与人工冻结。旧 input.json 也可导入。
4. `/sdd-run <run-id>` 调度已冻结且依赖就绪的模块，单模块也可用 `/sdd-module <run-id> <module-id>`。模块内自动推进到完成、挂起或预算耗尽。
5. 用 `/sdd-status <run-id>` 冷读状态；用 `/sdd-resume <run-id> [module-id] [decision.json绝对路径]` 恢复；用 `/sdd-audit <run-id>` 执行独立遗留复核与收尾审阅。
6. 全局审计通过后，`/sdd-archive <run-id> <decision.json绝对路径>` 验证人类交付授权并同步、归档 OpenSpec。授权必须绑定具体版本。

这些 slash command 是待宿主加载的命令定义，未安装到用户配置；本包已提供本地 Ledger 控制器、阶段校验和测试调用适配器；没有常驻 Agent 调度服务或内置业务测试。本地控制器实现事件提交、单写者和模块资源占用检查；宿主仍须提供身份认证、写权限隔离、Agent 派发与项目真实测试适配器。具体能力见 [本地运行指南](skills/migration-protocol/references/local-runtime.md)。仅加载 Markdown 不会产生操作系统级权限隔离。没有这些能力时应显式阻塞，不能宣称端到端迁移已执行。

## 二方库与已有能力

迁移规划先评估目标项目已有能力及用户指定的其他项目模块：**来源登记 → 功能语义抽取 → 结合需求映射 → 冻结接入/适配 tasks → Coding → 真实依赖验证**。GO 建目录，父 MO 统一复用分工，子 MO 形成 reuse/adapt/reference/new 决策；依赖变化按消费者范围复测，最终由 Auditor 裁决。

用户指定其他项目时，通过项目配置的可选 `reuse_sources` 保存 root/module_paths/用途；目标项目自动纳入评估。规则、配置实例及控制器边界见 [二方库复用协议](skills/migration-protocol/references/reuse-dependencies.md)。

全局 fidelity 要求：复用前与存量源码对应功能逐行为对齐，固定原行为、差异及复现 PATH/ASSERT；Coding 后 Main 验证真实生产链路并留证。接口相似或库自身通过不等于迁移通过。对齐记录使用 [reuse-fidelity.md](template/reuse-fidelity.md)，随 reuse-plan 冻结，MO/Auditor 按各自阶段验收。

## 流程图

按三层编排阅读 [完整图集](diagrams/README.md)：[总览](diagrams/workflow.svg) → [子 MO 执行与修复](diagrams/module-execution.svg) → [Auditor 跨模块处理](diagrams/auditor-closure.svg)，另见贯穿各阶段的 [二方库语义与复用](diagrams/reuse-dependencies.svg)。每张均提供 PNG 和可再生成的源文件。

## 目录

| 目录 | 用途 |
| --- | --- |
| `Agents/` | 10 个角色定义，含输入输出、边界、Skill 依赖与自查 |
| `skills/` | 共享协议与 10 个职责技能，按需读取 |
| `command/` | 9 个命令入口，负责上下文配置、参数、门控和派发 |
| `template/` | 全局输入、模块输入、六件套及诊断、测试、事件、人工决策等运行工件模板 |
| `diagrams/` | 三层编排总览、子 MO/Auditor 细节图及生成源文件 |

运行期在目标仓 `openspec/` 下实例化，包目录自身不存迁移状态。模块 ID 永久稳定，如 `M001`；OpenSpec change 名如 `migration-demo-m001-account`。新增模块只追加编号，不因排序改变历史 ID。

## 对现有 guidance 的适配

依据 [flow_spec.md](../flow_spec.md)、[dingpan 分析](../dingpan_harness_architecture_analysis.md) 与 [原 Agent 模板](../template/agent_template_guide.md)、[Skill 模板](../template/skills_template_guide.md)、[Command 模板](../template/command_template_guide.md)。本次用户明确要求优先，覆盖关系如下：

| 现有机制 | 本包机制及理由 |
| --- | --- |
| Command/Agent 分别写 `plan.md` | Ledger 唯一写事件与状态投影，杜绝并发双写；命令只提交请求 |
| 所有 Agent 不能调用其他 Agent | 叶子角色单步退出；编排角色提出派发事件，由宿主执行；Auditor 可经 Ledger 委派修复 |
| 每一步均人工确认 | 模块在冻结后有限自动循环；澄清冻结、核心架构/验收变更、主分支合并保留人工门禁 |
| 文件存在即可修正阶段为完成 | 校验文件、摘要、版本及已接受事件；文件存在不能证明通过 |
| 删除已存在文件再运行 | 使用不可变版本和事件恢复；不删除用户成果、不静默覆盖 |
| 运行失败测试后再实现 | 本次硬红线要求代码先生成才运行测试；测试设计和脚本准备前移，缺陷闭环保留真实 red→green 证据 |

因此本包是规格与测试设计前置的迁移流程，不声称每个成功路径都做过严格 test-first RED；首次即 Green 时记录 `red_evidence: not-observed`，不伪造失败。`plan` 指文档澄清阶段，不假定宿主能自动切换某产品的 Plan Mode。

## OpenSpec 边界

采用标准 `openspec/specs/<capability>/spec.md` 与 `openspec/changes/<change>/specs/<capability>/spec.md` 的基线/增量结构；proposal、design、tasks 使用标准语义。`status.md`、`checklist.md`、Ledger 与强制冻结门禁是本包扩展，不是 OpenSpec 内置执行能力。参见 [官方概念](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md) 与 [CLI 文档](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)（核对日期 2026-09-16）。详细映射见 [OpenSpec 协议](skills/migration-protocol/references/openspec.md)。

## 验证范围

本包可检查入口引用、frontmatter、JSON 模板与流程契约；真实迁移须在填写技术栈、宿主适配和真实测试命令后验证。推荐的行为验收场景见 [workflow-verification.md](template/workflow-verification.md)。

## P1–P4 本地实现

- 人类 decision_envelope 与当前执行 freeze 分开绑定。
- `ledger.py` 提供单写事件事务、游标投影、恢复与显式追加预算。
- `contracts.py` 在提交与验收时校验阶段结果，拒绝缺失/过期证据。
- `execute_test.py` 在已接受代码上执行真实项目适配器并保留回执。
- 源码闭环、目标可行性、owner 路由与会话冷恢复进入协议。

[P6 验证记录](VERIFICATION.md) 说明实际测试与边界；KMP 专项 P5 未接入。

## 控制流增强（2026-09-17）

再次对照 android-to-kmp-lean-orchestrator，将下一角色/动作游标、精确恢复、严格阶段结果接收和审计轮次生命周期接入本地编排。`status` 现在提供 next_steps、ready_modules、global_next_step；所有推进仍走 Ledger 事务。详见 [运行指南](skills/migration-protocol/references/local-runtime.md)。

## 当前本地能力补齐

实现前 global-plan 覆盖验收；Red/Yellow 本地优先一轮修复，确认的依赖/外围问题直接进入 waiting-auditor；problem-audit 可在模块未全 Green 时统一复核，最终 audit 仍执行完整全局门禁。Ledger 自动生成 OpenSpec 六件套与可复用修复 memory。精确操作与兼容性见 [本地运行指南](skills/migration-protocol/references/local-runtime.md)。

## 并行 MO 独立执行与统一收尾

GO 拆分并登记模块后，各 MO 独立执行和验收。某个模块失败/挂起时，其他无关模块继续，已完成模块保留有效 Green；全局 Red 只是聚合结论。宿主逐个收集结果，直到完整 registry 中全部模块完成或基于自身证据明确挂起、所有 worker 结束且无可推进动作，才统一启动 Auditor。详见 [隔离与全量收尾规则](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 模块 Coding 与 Testing 顺序

项目级和指定单模块均执行：

```text
Coding → MO 接受代码 → Testing
  ├─ Green → MO 核验 DoD、验收记录
  └─ 可修复 Red/Yellow → 诊断 → MO 自动派发一轮 Fixer
                       → 接受补丁 → Testing 正式复测
                       ├─ Green → MO 核验 DoD、验收记录
                       └─ 仍非 Green → 记录根因/memory，等待 Auditor
```

已确认依赖/外围问题直接记录并等待 Auditor。Fixer 自测不能代替正式 Testing；所有模块本轮结束后才统一启动 Auditor，首轮 Green 同样保留最终独立审计。

## Auditor 默认收尾

所有模块本轮 completed 或明确挂起，且无在途 worker/可推进工作后，统一启动 Auditor 收集 Red/Yellow。按 finding 读取 SPEC/路径、分析根因并路由到对应 Fixer；按依赖交错执行修复和完整 Testing，支持多 owner 与受影响中间模块。失败只挂起关联分支，独立分支继续；汇总后由人工批准 audit-release，再进入受控恢复。subagent 和 Used Skills 由宿主实际启动。详见 [运行契约](skills/migration-protocol/references/local-runtime.md#当前默认-auditor-收尾修复后验证失败待人工)。


## Harmony 自动测试内核

测试模块已迁入 HarmonyAgenticTesting 的 Planner/Executor/Verify、五类截图/视频验证、录制回放与重规划、压缩/反思/XPath、6 个技能及原始报告。通过完整冻结 PATH 输入、逐 ASSERT 证据输出接入现有 Ledger；保留普通项目 Main。缺依赖/证据与不明确结论为 Yellow，历史回放通过不能代替本轮验证。

入口：[Harmony 运行协议与能力映射](skills/migration-test/references/harmony-runtime.md)，[配置模板](template/harmony-config.json)，[验证记录](VERIFICATION.md)。Harmony 接入时 208 项本地/源回归通过；本轮收尾调度回归见验证记录；真实设备与模型的效果对照待指定用例后进行。

### 独立 uv 环境与默认 LLM

Harmony 已提供独立 [uv sandbox 与使用说明](skills/migration-test/runtime/harmony/README.md)：在该目录执行 `uv sync --locked`，配置本地 `.env`，再执行 `uv run --locked sandbox.py doctor`。默认复用 MobileAgenticOperator 的 `qwen3.7-plus`（Planner/Executor/Verify）、`deepseek-v4-flash-0731`（XMind）和 DashScope endpoint；支持公共/角色密钥、`--config`、`--env-file`、`--device` 覆盖。真实 `.env` 与 `.venv` 均已忽略，只提交无密钥示例与公开配置。uv 提供依赖隔离，宿主继续负责设备和执行权限。

测试覆盖按模块 CASE → automation PATH → ASSERT 追溯；每个 CASE 必须有自动化路径，不能用 build PATH 代替业务覆盖。独立调试不产生 Ledger 验收，正式执行仍经 assignment、host receipt、完整 scope 汇总及 MO/Auditor 验收。完整命令、缺环境 Yellow 分流与模块边界见上述 README。

## 切片输入与验收责任

默认由 Agent 决定切片粒度；global-input 的可选 module_slicing 支持人工模块方案导入。完整功能 use case 可按一级/二级功能目录划分 module，再分析 scope/测试列表并生成 SPEC。跨模块或不确定的业务边界交人工决策。模块阶段由 MO 唯一验收，审计阶段由 Auditor 唯一验收；完整 Green 且已有门禁满足后直接记录。字段示例与约束见 [切片规约](skills/migration-global/references/slicing.md)。

## 单个功能模块入口

默认 [global-input.json](template/global-input.json) 的 `entry_mode=project`：直接指定完整项目，GO 识别各功能模块及子功能。`single-module` 选择其中一个特定功能；两种模式都在父 MO 阶段继续拆分子功能。

单模块只是同一入口的两个参数：`entry_mode=single-module` 与 `module_name`（如“用户登录”）。沿用当前项目输入，用户无需提供模块描述、scope、模块代码路径、SPEC 或 Testing list；全部由 Global 根据模块名识别生成。[single-module-input.json](template/single-module-input.json) 仅展示这两个参数，不是独立运行资料包。

完整流程：用户选择项目或根功能 → **GO 划分根模块 scope + 上下文 + SPEC 草稿 / Testing list** → **父 MO 认领，在范围内拆子模块 scope + 上下文 / GO 审核登记** → **独立子 MO 拆 tasks**，组织六件套、测试路径、冻结、实现、自测 → **父 MO 等待并汇总全部孩子** → **GO 统一启动 Auditor**。父子 MO 都读取全局存量/目标代码、架构规范、知识与分工，检查复用及交叉工作。详见 [父子 MO 协议](skills/migration-protocol/references/module-decomposition.md)。

宿主接入命令后，可按以下阶段执行（路径和 run-id 为示例，冻结前仍需真实澄清与批准）：

```text
/sdd-init --mode single-module --module-name "用户登录"
/sdd-plan <初始化返回的run-id> <Global生成的module-id>
/sdd-run <初始化返回的run-id>
/sdd-status <初始化返回的run-id>
/sdd-audit <初始化返回的run-id>
```

首轮 Green 仍需最终独立审计，Red/Yellow 按相同一轮修复与审计收尾策略处理。`/sdd-module` 是推进已注册模块的命令；新单模块运行从 `/sdd-init` 开始。字段、独立性与范围限制见 [切片规约](skills/migration-global/references/slicing.md#项目级与单模块入口)。

## 持久化项目上下文

已提供实际 [project_context.py](skills/migration-ledger/scripts/project_context.py)：init/update/show/history/prepare。首次输入保存项目配置，更新只合并明确字段并保留版本；本次模块选择和临时 overrides 不写回默认值。prepare 固化配置及文档副本，Ledger init 绑定该快照；新配置只影响新运行，旧运行保持原版本。

例如“目标工程改为 /workspace/new-target”更新项目配置；随后“single-module，用户登录”使用新版本，由 Global 生成全部模块输入和规格/测试。跨模块或不确定业务边界仍按原规则澄清。

输入结构、更新语义、运行绑定和 CLI 示例见 [项目上下文协议](skills/migration-protocol/references/project-context.md)。自然语言提取、生成 SPEC 与真正派发 Agent 仍由宿主完成。

## 按阶段验证上下文就绪

新运行已在 GO 发现/覆盖规划、父 MO 拆分、子 SPEC 冻结、Coding/Testing/Fixer 派发及 Auditor 分析/裁决/最终测试中加入上下文门禁。执行者只读预检 → Ledger context-submit → 原节点验收；缺项/过期拒绝推进，按原阻塞机制恢复。查看 [节点与角色清单](skills/migration-protocol/references/context-readiness.md) 和 [报告模板](template/context-readiness.json)。

## 功能清单来源与完备性

默认从测试用例汇总形成完整功能列表并切片；缺少汇总则先理解存量源码、完整抽取功能，再生成需求与测试草案。每项功能必须可追溯到来源、需求/CASE 和执行模块；未知、冲突或可能遗漏立即交人工，未解决不得接受规划。见 [切片规范](skills/migration-global/references/slicing.md) 与 [功能清单模板](template/feature-inventory.json)。

## Test-Runner：先编译，再自动化

新运行将验证拆为 build 与 automation。构建命令优先用户指定，默认搜索目标 Gradle wrapper/脚本并评估 assemble；错误留根因，经 Fixer 后重新构建。仅自动化环境无法启动时，记录每条用例 Yellow/未执行并收尾，其他并行及可消费当前代码的下游继续；Auditor 最终可输出 completed-with-unverified-tests，质量仍 Yellow。配置、操作和恢复见 [完整协议](skills/migration-protocol/references/build-automation.md)。

### Auditor 遗留复核范围

所有 MO 本轮实现/测试收尾后，Auditor 统一收集 Red/Yellow，依据对应 SPEC/CASE/PATH 分析、委派一轮必要修复并复核；仍失败输出根因待人工。有效且无关的 Green 不重跑。`global_test_paths: []` 不阻止启动；无待测路径只提交独立 `audit-review`，不要求自动化环境。旧 run 可直接用更新后的 Ledger 查询下一步，无需重新 init。细则与恢复见 [审计范围协议](skills/migration-protocol/references/audit-scope.md)。

### 父 MO 名称与 GO 收尾报告

父 MO 统一命名 `parent-mo-M010`（模块 M010），派发与恢复均保持一致。GO 在本轮收尾后提供全部测试用例状态表，Red/Yellow 附根因、责任方、下一步和证据。Ledger 自动生成 `<run_root>/reports/migration-report.md` / `.json`，由 `status.migration_report` 定位；未执行/过期证据保留 Yellow。详见 [GO 报告协议](skills/migration-protocol/references/migration-report.md)。

## UI → Logic → Adhesive → Resource 深度切片

GO 读取上下文/功能清单 → 划分模块 → 模块四维分析；父 MO 认领并读取模块实现/分析等上下文 → 划分子模块 → 子模块四维分析；子 MO 认领并读取子模块实现/分析等上下文 → 划分任务 → 任务四维分析 → 冻结/实现。范围先确定，四维分析直接指导实现，完整关联 TASK/PATH/ASSERT。各维度按实际功能决定 applicable / 有证据的 not-applicable，未知项禁止冻结。分析顺序不强制编码顺序，不改变业务模块划分。参见 [控制节点、字段与案例](skills/migration-protocol/references/dimension-slicing.md)，[分析模板](template/dimension-analysis.json)。

## 运行停滞与恢复

全量分析检查在 global-plan 接受时执行；运行期只校验当前模块、父级分配及实际依赖。invalidate 保留旧证据并清空当前旧 plan，下一步明确为重新规划或 GO 分配审查。`ledger.py status` 返回 `workflow_progress`，同步生成 `ledger/progress.json`、`reports/workflow-attention.md`：列出阻塞原因/owner/证据、可推进动作、worker 无进展与人工提醒。

宿主须在 ACK/拒绝/worker 返回后刷新状态，等待期间至少每 60 秒检查；900 秒无作用域事件默认提醒，不自动停进程或放锁。仅自动化环境缺失仍走 Yellow 缺测收尾，其他任务及 Auditor 继续。无后台 watchdog，人工通知与真实调度由宿主落实。详见 [进度恢复协议](skills/migration-protocol/references/progress-recovery.md)。
