# 项目上下文：初始化、更新与运行时固化

## 总则

宿主先按本协议读取/初始化/更新当前项目配置，再 prepare 固化本轮版本。Global 生成完整输入后，Ledger init 绑定 project_context_ref；下游只读 Ledger 引用的本轮快照，不追随 mutable project-context.json。用户明确更新直接保存，运行选择和临时 overrides 不写回项目默认值。项目配置不是模块状态总线。

## 三层数据

1. 项目配置：跨运行复用的代码根目录、架构/需求/用例/规则文档路径、测试执行器、宿主配置和默认预算。模板 [project-context.json](../../../template/project-context.json) 是 `config` 内容。
2. 本次请求：run_id、entry_mode、module_name 和明确的临时 overrides。默认 project；single-module 只需模式和模块名，不能将本次模块选择保存成项目默认值。
3. 运行快照：启动时固定的项目版本、有效配置、文档副本和本次选择，供 GO 分析需求/CASE、叶子角色规划实施与测试，并供下游持续读取。

自然语言解析、项目识别和真实 Agent 派发由宿主完成。[project_context.py](../../migration-ledger/scripts/project_context.py) 实际实现配置保存、增量更新、历史、快照与校验；它不生成业务 SPEC 或测试。

## 固定位置与身份

项目配置目录是 `<workspace_root>/.sdd-migration`。初始化未提供 workspace_root 时取配置目录父级并持久化；CLI `--root` 指向该配置目录，后续启动显式传入，避免 cwd 改变导致误选项目。一个目录对应一个稳定 project_id；宿主先从当前项目定位目录，再读配置。多项目不能共用同一个配置文件；项目不明确时先定位，不套用其他项目上下文。配置目录独立于 legacy/target，目标路径更新不搬迁配置。workspace_root 与配置目录必须对应，不能以 update/override 改位置。新 run 自动使用同级 .sdd-runs；同级 openspec 以 run_id 隔离，见 [留存布局](storage-layout.md)。

```text
<工作目录>/.sdd-migration/
  project-context.json           # 当前已提交记录：project_id/revision/config/来源
  history/<sha256>.json           # 不可变历史版本，previous_ref 串联
  sources/<sha256>.*             # 用户输入来源的副本
  .context.lock                  # 单写者文件锁
  runs/<run_id>.json              # 不可变位置索引，不记录模块状态
  experience/                    # 经验库
    lessons.json                 # 各 run 的经验块
    retrospect.jsonl             # 采集回执流水
<workspace_root>/.sdd-runs/<run_id>/
  context/snapshot.json           # 本轮冻结上下文
  context/files/<sha256>.*        # 本轮架构、规则、来源等证据副本
  context/files/<sha256>.links.json # 原路径、原始副本、可读副本的版本映射与未解析链接
  context/files/linked/<bundle-hash>/<source-hash>.md # 重定位链接的知识文档，支持循环引用
  ledger/events.jsonl             # 原有迁移事件总线
```

项目配置由宿主唯一写入，Global 读取；worker 不得改项目配置，也不得用它私传执行状态。init/update/prepare 需要宿主绑定的 role=host、instance_id；本地 CLI 的 host-context 由宿主保护，不提供额外身份认证。show/history 只读。配置记录不是运行 Ledger 的替代品，模块状态和角色交接仍只经过 Ledger。

## 初始化和增量更新

宿主从用户输入提取明确字段，用 [请求模板](../../../template/project-context-request.json) 调用 init/update。首次用 expected_revision=0，后续读取当前 revision 再更新；request_id 对同一请求保持稳定。保存用户原话/文件到受控路径，以 source_ref 固定真实来源。

- 只更改 patch 中明确出现的字段；嵌套对象递归合并，数组整体替换。
- `null` 表示用户明确要求删除该字段；缺失字段保持原值。不得把“未提供”翻译为 null 删除旧配置。
- 普通明确更新直接写入，不增加一次确认；“仅本次”进入 run-request.overrides，不持久化。
- 项目 ID 不可改；模块名、run_id、SPEC、生成的测试列表和运行状态不能写入项目配置。
- 同 request_id+内容+宿主身份重试返回原 revision；同 ID 内容不同或过期 revision 拒绝；并发由锁和 revision 控制。
- 缺少部分共享配置时允许先保存；prepare 要求可用的 legacy/target 目录与架构文档，其余由后续门禁检查，缺少时如实阻塞。
- 写历史工件后原子替换当前文件即提交；未引用工件不算更新，history 仅遍历已提交链；禁止手工改当前文件绕过版本记录。

默认值存放在 config.defaults：entry_mode 固定 project，另有 budgets 与 quality_gates（字段见模板）。test_adapter 与 input 中的结构一致（`adapters` 按平台给 argv；`harmony_reference` 给 init 准备 Harmony sandbox 的绝对 config/env_file），runtime 只放 model_routing。配置只引用宿主环境或凭证名称，不在模板中放凭证值。

质量门开关都在 `defaults.quality_gates`，均 bool 默认 false：`git_checkpoint`（模块 Git 检查点）、`write_scope_check`（写范围核验）、`fixer_self_diagnosis`（本地轮 Fixer 自诊断，开启后不再为本地轮启动独立 Diagnostician）、`dependency_resolution_required`（Foundation 冻结，例如 `{"defaults":{"quality_gates":{"dependency_resolution_required":true}}}`）；模块累计修复预算为 `defaults.budgets.max_fix_rounds`（默认 3，各类失败共用）。prepare 把这些值固化到快照与 Global input，init 按快照继承，不得在 prepared init 中降级或覆盖。开启 Foundation 冻结后，无新增依赖的切片也须保留 not-required 解析证据，见 [知识执行与冻结](engineering-disciplines.md)。

## 运行时固化

宿主先保存本次明确的项目更新，再调用 prepare：

1. 读取最新已提交项目版本；可用 run-request.expected_revision 指定必须匹配的版本。
2. 合并本次 overrides；读取 entry_mode/module_name，分配 run_id。验证目录、模式与配置。
3. 在独立 run_root 保存 snapshot.json，固定 project_id、project_revision、原配置摘要、有效配置、本次选择与用户来源；架构/需求/用例/规则和测试环境说明复制到本轮证据目录。JSON 来源按不透明文件保存，不能被误当作需要跟随内嵌路径的 Ledger 请求。
4. prepare 返回 project_context_ref 和 `input`；input 就是 Ledger init 的载荷形状，作为 Global 的分析输入，其中 global_spec/需求/CASE/global_paths 待 Global 生成。宿主将 Global 补齐的 input 保存为 `<run_root>/input.json`，原样作为 init 载荷提交；未生成完整非空规范/用例前不得 init。
5. input 已含 project_context_ref、快照对应的 legacy_root/target_root/new_architecture、entry_mode/module_name 与预算；Global 补齐 global_spec/requirement_ids/case_ids/global_paths。single_module_id 由 Global 生成，标识选定根功能；父 MO 随后拆分子功能，用户仍只输入模块名。
6. Ledger 校验快照所属 run/root、路径、模式/模块名、架构引用及预算。运行状态保存 project_id/project_revision/project_context_ref；已有快照时不能漏传引用。后续事务和 status 校验冻结证据，禁止换用最新配置。

prepare 同一请求重试从 `.sdd-migration/runs/<run_id>.json` 找回原位置并返回原快照，即使项目配置已经更新。相同 run_id 指向另一目录会被拒绝；新任务必须使用新 run_id。相同 run_root 的新请求不能覆盖旧快照；初始化过的旧运行也不能后补快照伪造启动依据。prepare 的返回只代表上下文已固化，init ACK 才代表运行进入 Ledger。

项目 defaults 更新影响后续新任务；当前任务采用新架构、知识或构建/测试配置时，经 [同 Run 上游修订](progress-recovery.md#同-run-上游修订) 发布 context/revisions，保留初始快照；只读来源追加走 source-review/reconfigure-sources，不重跑 prepare。

快照固定配置和引用文档；业务源码、执行器与设备环境仍由 code baseline/测试执行回执验证，不声称复制了整个工程。

### context/files 的跨文件链接

prepare 递归固化 Markdown 本地文件链接（文档、代码、图片）。原始字节存 `<sha256>.*`；重定位 Markdown 生成版本化阅读副本，`source_refs` 指向可读版，`link_manifest_ref` 记录原始与可读版本映射。

支持相对/绝对/file://、行内/引用链接与 HTML href/src，保留锚点；代码块与远程 URL 不改写；链接代码作知识基线，不代 live baseline。

循环引用经 bundle 地址重写，sha256 以 manifest 为准；缺失或越界（256文件/32MiB）记 `document_link_warnings`，未固化链接保留原绝对路径；快照不原地修改，原始 artifacts 用于审计，跨文件阅读用 source_refs。

## CLI

以下是实际 Python 命令；`/sdd-context`、`/sdd-init` 是宿主需接入的命令定义。配置目录参数指向 `.sdd-migration`；prepare 按 run_id 派生 `.sdd-runs/<run_id>`，返回 run_root/storage_layout 供宿主调用 Ledger；请求 JSON 由宿主按真实用户输入整理。

```bash
project_context.py <init|update|prepare> \
  --root <工作目录>/.sdd-migration --request <request.json> --host-context <host.json>
project_context.py <show|history> --root <工作目录>/.sdd-migration
```

`target_resources`（copy 与 parameters 各须声明或 declined）随项目配置保存并固化进每次运行，字段见 [target-resources.json](../../../template/target-resources.json) 与 [搬运](resource-transfer.md#总则)。

[run-request.json](../../../template/run-request.json) 中的元数据、项目标识、来源引用由宿主生成；用户的单模块选择仍只有 `single-module + 功能模块名`。

## 父子共同规划视野与知识资料

可选 knowledge_paths 是知识文档或其目录（wiki 导出，递归取 Markdown）的绝对路径数组，整体替换；prepare 复制每份并绑定摘要到 source_refs.knowledge_paths，旧运行读原快照；往次 run 的人工知识答复随经验库沉淀，下次 prepare 自动并入。父子 MO 经 planning_context 读取，角色可用 knowledge-query 的 project 模式查；都没有的知识登 knowledge-need，由人以 kind=knowledge 决定补充并带来源。全局代码目录只读用于理解和复用检查，目标源码变化仍受 baseline/锁/冻结约束；缺必要知识或未声明公共能力 owner 时先记录问题，不凭局部信息重复实现。

## 用户参考媒体

可选 reference_media 数组（元素见 [reference-media.json](../../../template/reference-media.json)），整体替换；prepare 复制并绑定 hash 到 source_refs.reference_media。持有其 CASE 的叶子在分配包 `reference_media` 读到它们并以之为就绪证据。截图是存量不可预览界面的基线：UI 项以 `visual_mode: user-reference` + `baseline_refs` 引用该 CASE 的截图，不得退回 source-only；visual PATH 的 `baseline_ref` 指向它。录屏是功能 PATH 的交互预期，以 `reference_media_ids` 引用，`media_marks` 可标注时间段；截图还可作断言的 `reference_media_id` 参考图。用户展示过的用户可见 CASE 没有 PATH 引用对应媒体即记欠项（已声明设备缺口除外）；规划步骤带 `media_due`（本叶尚未被引用的媒体），持有媒体的叶子卡片带本节；诊断/修复步骤并列预期媒体与实际媒体；报告按媒体列持有叶子、引用 PATH 与状态。role=target-expectation（设计稿、目标截图）在其覆盖的界面取代存量基线作视觉对齐目标，行为仍以存量为准：UI 项以 user-reference 引用它（存量可预览亦然），design 须引用其 media_id；与存量的差异由报告保真限制（target-expectation）披露，不交人；对照它的视觉 Red 走 Fixer，与冻结 SPEC 冲突走 runtime-spec-variant-conflict 交人。

## 存量预览

legacy_preview（[legacy-preview.json](../../../template/legacy-preview.json)）声明存量 App 怎样跑：kind=android-device|android-emulator|vm（adb 可见的 device.serial、app_id、artifact 或 build、可选 launch 与 navigator；harmony-device 同形，serial 为 hdc 目标、launch 为 ability，没有真机时给 boot.argv（鸿蒙无标准命令行模拟器）；没有真机时 device 带 avd 或 boot.argv，serial 不应答即启动模拟器并等开机）、browser（url，可选 viewport）或 none（reason）；UI 登记前须声明，prepare 记包哈希；init/update/prepare 返回 `open_statements`（含目标验证设备与 target_resources），status 以 statement-required 提示到声明为止。`test_adapter.device` 按平台给目标预览（serial 与 avd/boot，可带目标 app_id 与 launch；或 url 与 viewport），init 据此写出运行环境文件，骨架据此预填 visual PATH 的应用与入口。声明即可执行性：kind≠none 的界面须有 runtime 捕获（legacy-capture）或用户截图，未捕获者写 `ui_evidence.capture_gap`（reason、evidence_refs）进报告保真限制；none 只能 source-only 或用户截图。报告逐界面写基线来源。

## 二方库/其他项目模块来源

新增可选 reuse_sources 数组，元素使用 [reuse-source.json](../../../template/reuse-source.json)：source_id、绝对 root、范围内 module_paths、description。目标项目 TARGET 自动作为来源；外部输入仍只读。init/update 保存并按数组替换规则更新，prepare 检查目录/模块可访问并将来源配置固化，旧运行不跟随新配置。prepared_input 输出 reuse_required=true；bind_run 从快照恢复来源，显式不匹配输入被拒绝。源码不全文快照，语义抽取及选中 provider/version 的内容证据另由 Agent 经 Ledger 记录；详见 [复用协议](reuse-dependencies.md)。

## 独立构建配置

可选 build 保存 argv/cwd/timeout_seconds/environment_ref，按原协议更新，prepare 固化命令与环境文档；未指定命令时 GO 搜索构建脚本、默认评估 Gradle assemble。split_testing_required=true，缺自动化环境不能关闭编译门禁。详见 [构建与自动化协议](build-automation.md)。

## 跨运行经验沉淀与复用

跨 run 的分析/切分经验只经经验库抽象复用，不手工拷入新 Run：
1. **经验沉淀**：收尾审计/父汇总 ACK 从事件采集观察（切分/边界调整、重规划、修复模式、阻塞与解除依据、一次冻结改交计划或同因被拒三次），失败为 pending 可重试；配置 `experience_root`（绝对目录）则多工作区共用一库，块名 `<project_id>/<run_id>`。缺适用条件、根因、策略、结果或下次检查项的观察待 `/sdd-retrospect` 抽象，经 retrospect 或 run-review 的 lessons_ref 提交。每次采集重生成切分技能 `skills/migration-slicing-experience/SKILL.md`（多 run 印证的教训在前，内容变才升版）。run 内定论的 target_resources 与 test_adapter.device 随采集入库，下一 Run 的 prepare 在项目配置未声明时取用。
2. **规划指导**：prepare 只固化完整抽象经验，原始观察留存供复盘，不臆造根因；本 Run 的不可变 history_refs 纳入通用及关联叶子经验，预检绑定版本。prepare 一并固化切分技能：登记、全局规划、拆分与接受、上溯和上游修订步骤以游标 slicing_skill 给出，宿主按技能加载。收尾的全局游标在有未抽象观察或切分信号（成链、过半等待、界面逻辑分属、一次冻结改交达三次）且尚无复盘时给出 retrospective_due，由统一 Auditor 按 retrospective.json 抽象并提交 retrospect。
