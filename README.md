# SDD-TDD-Migration

按功能切片迁移的 Agent 工作流包：9 个执行/治理角色 + 1 个 Ledger。输入整体规范、新架构、存量代码路径、目标代码路径及整体测试用例，先拆分模块和用例，再并行迁移，最后独立审计。

## 从这里开始

可选旁路 [Watchdog](skills/migration-protocol/references/watchdog.md) 提供 `check/watch` 状态监听与通知、`ack` 交付确认；未确认通知可重放，Host 按 notice_id 去重展示。支持真实本机进程检查及宿主 API 状态导出；未接入时显示 unknown。不会自动启动、派发 Agent、提交恢复操作或影响迁移门禁。

1. 读取 [AGENTS.md](AGENTS.md)，按角色索引渐进加载。
2. 首次提供项目资料，宿主根据 [project-context.json](template/project-context.json) 保存到固定 `<workspace_root>/.sdd-migration/project-context.json`（首次未指定 workspace_root 时取配置目录父级）；后续按该目录读取，用户明确更新时增量保存。无需每次重填运行输入。
3. 在支持此包的宿主中执行 `/sdd-init`，先固定项目配置和本次请求快照，再由 Global 生成 [运行输入](template/global-input.json)、SPEC/Testing list、账本和模块规划；`/sdd-plan <run-id> <module-id>` 完成正式六件套与人工冻结。旧 input.json 也可导入。
4. `/sdd-run <run-id>` 调度已冻结且依赖就绪的模块，单模块也可用 `/sdd-module <run-id> <module-id>`。模块内自动推进到完成、挂起或预算耗尽。
5. 用 `/sdd-status <run-id>` 冷读状态；用 `/sdd-resume <run-id> [module-id] [decision.json绝对路径]` 恢复；用 `/sdd-audit <run-id>` 执行独立遗留复核与收尾审阅。
6. 全局审计通过后，`/sdd-archive <run-id> <decision.json绝对路径>` 验证人类交付授权并同步、归档 OpenSpec。授权必须绑定具体版本。

这些 slash command 是待宿主加载的命令定义，未安装到用户配置；本包已提供本地 Ledger 控制器、阶段校验和测试调用适配器；没有常驻 Agent 调度服务或内置业务测试。本地控制器实现事件提交、单写者和模块资源占用检查；宿主仍须提供身份认证、写权限隔离、Agent 派发与项目真实测试适配器。具体能力见 [本地运行指南](skills/migration-protocol/references/local-runtime.md)。仅加载 Markdown 不会产生操作系统级权限隔离。没有这些能力时应显式阻塞，不能宣称端到端迁移已执行。

要在其他仓库真实跑起来，按 [宿主接入契约](skills/migration-protocol/references/host-integration.md) 接入真实角色派发与执行回执。推进按 global/module 范围运行 `/sdd-verify`，巡检用 projection、交付用 final；核验只证明记录和投影一致，无关模块视图错误不阻塞当前 MO，也不能由核验通过推断实际执行或功能全绿。UI 分析、资源转换与受限视觉取证按 [领域工具受限接入](skills/migration-protocol/references/domain-tools.md) 使用，保持既有角色、Ledger 和修复预算。

## 流程图

编码前的独立测试设计通过 Ledger `assign(mode=design) → submit → MO accept` 留证，再绑定 Spec plan/freeze；无代码阶段只设计，不执行或记录通过。该门禁由 prepare 固定开启。见 [设计交接](skills/migration-protocol/references/testing.md#编码前设计交接)。

按三层编排阅读 [完整图集](diagrams/README.md)：[总览](diagrams/workflow.svg) → [子 MO 执行与修复](diagrams/module-execution.svg) → [Auditor 跨模块处理](diagrams/auditor-closure.svg)，另见贯穿各阶段的 [二方库语义与复用](diagrams/reuse-dependencies.svg)。每张均提供 PNG 和可再生成的源文件。

## 目录

| 目录 | 用途 |
| --- | --- |
| `Agents/` | 10 个角色定义，含输入输出、边界、Skill 依赖与自查 |
| `skills/` | 共享协议与 10 个职责技能，按需读取 |
| `command/` | 10 个命令入口，负责上下文配置、参数、门控、派发与投影完整性核验 |
| `template/` | 全局输入、模块输入、六件套及诊断、测试、事件、人工决策等运行工件模板 |
| `diagrams/` | 三层编排总览、子 MO/Auditor 细节图及生成源文件 |

运行期资产集中在固定 `workspace_root`，其下 `.sdd-migration`（长期配置）、`.sdd-runs/<run_id>`（运行证据）、`openspec`（规格与状态中枢）顶层并列；包目录自身不存迁移状态。Harmony 执行统一在 `.sdd-runs/<run_id>/runs/harmony/`（automation/sandbox），构建资产在 runs/build；临时文件归 runner，结束清理，失败留存原因。项目模型参考配置/凭证在 `.sdd-migration/harmony/`；Test-Runner 首次准备时复制到本轮 `runs/harmony/sandbox/environment/`，各模块共享本轮副本。入口为 `openspec/runs/<run_id>/workflow.md`。见 [完整留存布局与二次启动](skills/migration-protocol/references/storage-layout.md)。模块 ID 永久稳定，如 `M001`；OpenSpec change 名如 `migration-demo-m001`。新增模块只追加编号，不因排序改变历史 ID。顶层 `openspec` 是 prepare→init→apply 真实跑通后的投影，不能手写；最终交付用只读门禁 `verify_openspec.py --root <run> --scope final` 核验投影与正式收尾报告；缺事件证据时恢复其有效来源，不由核验结果推断真实派发或功能通过，细则见 [投影完整性收尾门禁](skills/migration-protocol/references/storage-layout.md#openspec-投影完整性收尾门禁)。

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

## 验证范围

本包可检查入口引用、frontmatter、JSON 模板与流程契约；真实迁移须在填写技术栈、宿主适配和真实测试命令后验证。推荐的行为验收场景见 [workflow-verification.md](template/workflow-verification.md)。协议总量与单文件大小受 `reading.py` 的 PROTOCOL_BUDGET/FILE_BUDGET 棘轮约束，阅读卡另有 60KB 预算：新增规则写入其专题协议并合并重复表述，不在运行指南中再追加一份。

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

## 专题速览

各专题的权威规则只在对应协议中陈述一次（`AGENTS.md` 的专题索引列出触发条件），这里只给方向：

| 专题 | 一句话 | 协议 |
| --- | --- | --- |
| 二方库与已有能力 | 复用必须逐行为对齐存量功能；能力目录显式 provider owner | [复用](skills/migration-protocol/references/reuse-dependencies.md)、[来源变更](skills/migration-protocol/references/source-changes.md) |
| OpenSpec 边界 | 标准基线/增量结构；status/checklist/Ledger 是本包扩展，Ledger 投影不可手改 | [OpenSpec](skills/migration-protocol/references/openspec.md) |
| 本地控制器与游标 | 单写事件事务、`status` 游标与阅读卡、恢复与显式追加预算 | [本地运行](skills/migration-protocol/references/local-runtime.md)、[宿主接入](skills/migration-protocol/references/host-integration.md) |
| 并行 MO 与统一收尾 | 各 MO 独立推进；全量收尾或闭包提前审计才启动 Auditor | [状态机](skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾) |
| Auditor | 先整体代码治理，再复核遗留；修复后验证，失败待人工 | [审计范围](skills/migration-protocol/references/audit-scope.md)、[代码治理](skills/migration-protocol/references/audit-code-review.md) |
| Harmony 自动测试 | 迁入的 Planner/Executor/Verify 内核，逐 ASSERT 证据接入 Ledger | [Harmony 运行](skills/migration-test/references/harmony-runtime.md) |
| 切片与功能清单 | 默认由 Agent 决定粒度；清单完整可追溯，疑问交人工 | [切片规约](skills/migration-global/references/slicing.md) |
| 项目上下文 | 首次保存，增量更新，每次运行 prepare 固化快照 | [项目上下文](skills/migration-protocol/references/project-context.md) |
| 上下文就绪 | 执行者只读预检 → context-submit → 原节点验收 | [上下文就绪](skills/migration-protocol/references/context-readiness.md) |
| 构建、单测、静态审查、自动化、视觉 | build → unit → static → automation → visual；自动化缺失仅 Yellow | [构建与自动化](skills/migration-protocol/references/build-automation.md)、[UI 保真](skills/migration-protocol/references/ui-fidelity.md) |
| 四维切片与语义模型 | UI → Logic → Adhesive → Resource 逐层映射到 TASK/PATH/ASSERT | [四维](skills/migration-protocol/references/dimension-slicing.md)、[语义抽取](skills/migration-protocol/references/semantic-extraction.md) |
| 阻塞感知与恢复 | 局部校验、invalidate 出口、进度信号；watchdog 只观察 | [恢复与进度](skills/migration-protocol/references/progress-recovery.md)、[watchdog](skills/migration-protocol/references/watchdog.md) |
| 埋点 | 有则迁移，无则有据 N/A 正常推进 | [埋点](skills/migration-protocol/references/telemetry.md) |
| 留存与资产根 | `.sdd-migration`、`.sdd-runs`、`openspec` 并列 | [留存文件系统](skills/migration-protocol/references/storage-layout.md) |

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

## 版本记录

协议、模板、脚本与测试只描述当前版本；不同版本之间的差异只在此处记录。旧版本的运行资产不做就地升级，需要继续迁移时以当前版本 prepare 新 run。

| 日期 | 主要变化 |
| --- | --- |
| 2026-10-02 | 编码前独立测试设计接入 Ledger 派发/提交/验收链；prepare 固定该门禁，plan/freeze 绑定同一份已接受设计；过期设计明确撤销或重新规划，保留历史证据。 |
| 2026-10-02 | 行为完整性：prepare 固定行为契约门禁；GO/父 MO/子 MO 行为闭包审阅；OpenSpec 派生 Scenario 索引与任务/断言追溯；单测核验当前 runner 的 JUnit 实际测试 ID、计数与报告证据。 |
| 2026-10-02 | 日志与追溯：执行期间持续留存分流日志、时间/字节索引及不完整标记；只读 trace 支持场景/路径/测试 ID、历史归档与分页；watchdog 可附输出观察，仍不改变业务状态。 |
| 2026-09-18 | 初始工作流：9+1 角色、Ledger 单写事件、冻结门禁、本地控制器 |
| 2026-09-19 | Test-Runner 先构建后自动化；Harmony 自动测试内核与独立 uv 环境 |
| 2026-09-20 | 自动化缺测 Yellow 收尾；父 MO 命名与用例报告；四维切片；同 run 来源追加；显式 provider owner |
| 2026-09-21 | Auditor 代码治理前置；埋点适用性；统一资产根与顶层 OpenSpec |
| 2026-09-22 ~ 09-24 | Watchdog 旁路通知、执行器中断收尾、OpenSpec 分范围核验、宿主接入契约 |
| 2026-09-25 | 机器可读语义模型；模型路由档位 |
| 2026-09-27 | UI 保真证据、受限领域工具 worker、精确资源策略、视觉对齐阶段、手势、HAP 绑定、Foundation 解析门禁；prepared run 默认开启 UI fidelity |
| 2026-10-01 | 模块控制器在规划/测试阶段的守卫增强；证据契约与复用目录统一为单一当前版本，删除旧版本兼容分支 |
| 2026-10-01 | 修复闭环与独立审查：可配置 build 本地修复轮次、作者自检、本地修复复用 Implementer 会话；build → static → automation 的静态规格闭合审查；按步骤阅读卡（单卡不超过 60KB）；轻量叶子、父级批量冻结信封、运行时变体冲突交人工；可选模块 Git 检查点 |
| 2026-10-01 | 降低流程成本：static 并入 build 派发（绿色叶子 21→19 事件、4→3 次派发）；会话/阅读卡采纳可审计；流程成本指标进入状态与报告；运行指南去重与协议体积棘轮；静态审查要求调用位置；依赖闭包空闲即可提前审计；可选全模块 Fixer 自诊断 |
| 2026-10-01 | 文档瘦身：角色定义与角色技能改为“专题义务”表，规则只在专题协议中陈述一次；协议总量 516KB → 476KB，最大阅读卡 49KB → 45KB，体积棘轮降至 480KB |
| 2026-10-01 | 补齐独立验证：逻辑单测关卡（与构建同一派发）、候选 App 崩溃判为缺陷、视觉修复聚焦、静态审查增加吞错反例与单测引用、可选写范围核验 |
| 2026-10-01 | 渐进式加载：规则不常驻——AGENTS.md 由 19KB 缩至 8KB（红线、角色索引、专题索引），专题规则在各自协议的“总则”中只陈述一次；阅读卡按操作与触发（UI/复用/埋点/轻量叶子）取小节，可物化为单文件，恢复会话只交新增小节，拒绝响应附小节指针；status 默认精简视图；角色通用约定并入共享协议；清除旧运行兼容叙述与三个恒开开关 |
| 2026-10-02 | 阅读卡再收窄：审计/GO 规划/MO 按操作取小节，技能文件只带执行规则，专题义务表与操作矩阵按行取；任意模块请求可报告会话与卡片以做增量交付；流程成本统计阅读卡字节；Harmony 写入路径约束移入 Harmony 运行协议；README 精简为入口与专题速览；清除变更日志口吻措辞 |
| 2026-10-02 | 堵住整份加载的入口：渲染后的阅读卡不再含指向整份协议的链接，小节引用改为可直接取用的选择器；游标轮询只带卡片大小并支持 `--since` 增量；步骤直接给出本步模板，不再读模板索引；Test-Runner 定义按测试阶段取块；会话持有协议文本超阈值时建议按 checkpoint 冷启动；请求级 `hint` 成为统一回报通道 |
