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
- 同 request_id+内容+宿主身份重试返回原 revision；同 ID 内容不同拒绝；过期 revision 拒绝并重读。并发通过锁和 revision 控制。
- 缺少部分共享配置时允许先保存已有输入；prepare 会要求可用的 legacy/target 目录与架构文档。测试适配器和宿主能力在后续对应门禁检查，缺少时如实阻塞，不能假测试。
- 写历史工件后原子替换当前文件；当前文件的替换是提交点。中断留下未引用工件不算更新；history 仅遍历已提交链。禁止手工修改当前文件绕过版本与来源记录。

请求例子（路径与摘要须替换，下面表示把目标工程改为新路径）：

```json
{
  "schema_version": 1,
  "project_id": "shop-migration",
  "request_id": "change-target-002",
  "expected_revision": 1,
  "patch": {"target_root": "/workspace/new-target"},
  "source_ref": {"path": "/workspace/migration/.sdd-migration/inputs/update-002.md", "sha256": "<实际摘要>"}
}
```

默认值存放在 config.defaults：entry_mode 固定 project，另有 budgets 与 quality_gates（字段见模板）。test_adapter 与 input 中的结构一致，runtime 只放 model_routing。配置只引用宿主环境或凭证名称，不在模板中放凭证值。

模块 Git 检查点开关为 `defaults.quality_gates.git_checkpoint`、写范围核验开关为 `write_scope_check`（均 bool，默认 false）；本地轮 Fixer 自诊断开关为 `defaults.quality_gates.fixer_self_diagnosis`（bool，默认 false，开启后不再为本地轮启动独立 Diagnostician）；模块累计修复预算用 `defaults.budgets.max_fix_rounds`（默认 3，各类失败共用）。Foundation 冻结开关只配置在 `defaults.quality_gates.dependency_resolution_required`，必须是 bool，默认 false，例如 `{"defaults":{"quality_gates":{"dependency_resolution_required":true}}}`。prepare 把该值固化到快照及派生 Global input，init 按快照继承，不能在 prepared init 中降级或另加顶层项目字段覆盖。Global input 中派生的顶层 dependency_resolution_required 是运行协议字段，不是第二个项目配置入口。开启后本切片无新增依赖/非适用目标也须保留明确 not-required 解析证据，见 [知识执行与冻结](engineering-disciplines.md)。

## 运行时固化

宿主先保存本次明确的项目更新，再调用 prepare：

1. 读取最新已提交项目版本；可用 run-request.expected_revision 指定必须匹配的版本。
2. 合并本次 overrides；读取 entry_mode/module_name，分配 run_id。验证目录、模式与配置。
3. 在独立 run_root 保存 snapshot.json，固定 project_id、project_revision、原配置摘要、有效配置、本次选择与用户来源；架构/需求/用例/规则和测试环境说明复制到本轮证据目录。JSON 来源按不透明文件保存，不能被误当作需要跟随内嵌路径的 Ledger 请求。
4. prepare 返回 project_context_ref 和 `input`；input 就是 Ledger init 的载荷形状，作为 Global 的分析输入，其中 global_spec/需求/CASE/global_paths 待 Global 生成。宿主将 Global 补齐的 input 保存为 `<run_root>/input.json`，原样作为 init 载荷提交；未生成完整非空规范/用例前不得 init。
5. input 已含 project_context_ref、快照对应的 legacy_root/target_root/new_architecture、entry_mode/module_name 与预算；Global 补齐 global_spec/requirement_ids/case_ids/global_paths。single_module_id 由 Global 生成，标识选定根功能；父 MO 随后拆分子功能，用户仍只输入模块名。
6. Ledger 校验快照所属 run/root、路径、模式/模块名、架构引用及预算。运行状态保存 project_id/project_revision/project_context_ref；已有快照时不能漏传引用。后续事务和 status 校验冻结证据，禁止换用最新配置。

prepare 同一请求重试从 `.sdd-migration/runs/<run_id>.json` 找回原位置并返回原快照，即使项目配置已经更新。相同 run_id 指向另一目录会被拒绝；新任务必须使用新 run_id。相同 run_root 的新请求不能覆盖旧快照；初始化过的旧运行也不能后补快照伪造启动依据。prepare 的返回只代表上下文已固化，init ACK 才代表运行进入 Ledger。

项目 defaults 更新影响后续新任务；当前任务采用新架构、知识、构建/测试/运行配置时，经 [同 Run 上游修订](progress-recovery.md#同-run-上游修订) 发布 context/revisions，保留初始快照。只读来源追加继续走 source-review/reconfigure-sources；不重跑 prepare 覆盖旧上下文。

快照固定配置和引用文档；业务源码、执行器二进制及设备环境仍由已有 code baseline/测试执行回执验证，不声称复制了整个工程或设备环境。

### context/files 的跨文件链接

prepare 递归固化 Markdown 本地文件链接（文档、代码、图片）。原始字节存 `<sha256>.*`；重定位 Markdown 生成版本化阅读副本，`source_refs` 指向可读版，`link_manifest_ref` 记录原始与可读版本映射。

支持相对/绝对/file://、行内/引用链接与 HTML href/src；保留标题/锚点。代码块与远程 URL 不改写。链接代码作知识基线，不代 live baseline。

循环引用经 bundle 地址重写，各文件实际 sha256 以 manifest 为准。缺失或越界（256文件/32MiB）记 `document_link_warnings`；未固化链接保留原绝对路径。快照不原地修改。原始 artifacts 继续用于审计；跨文件阅读使用 source_refs 与生成的 OpenSpec 视图。

## CLI

以下是实际 Python 命令；`/sdd-context`、`/sdd-init` 仍是宿主需接入的命令定义。配置目录参数指向 `.sdd-migration` 本身；prepare 根据请求 run_id 派生 `.sdd-runs/<run_id>`，返回 run_root/storage_layout，宿主使用返回值调用 Ledger。请求 JSON 由宿主根据真实用户输入整理。

```bash
python3 <package>/skills/migration-ledger/scripts/project_context.py <init|update|prepare> \
  --root <工作目录>/.sdd-migration --request <request.json> --host-context <host.json>
python3 <package>/skills/migration-ledger/scripts/project_context.py <show|history> --root <工作目录>/.sdd-migration
```

`target_resources`（目标资源目录、引用写法与参数文件模板）随项目配置保存并固化进每次运行，字段见 [target-resources.json](../../../template/target-resources.json) 与 [搬运](resource-transfer.md#总则)。

[run-request.json](../../../template/run-request.json) 中的元数据、项目标识、来源引用由宿主生成；用户的单模块选择仍只有 `single-module + 功能模块名`。

## 导入已有 global-input

新入口先初始化/更新项目配置再 prepare。用户提供旧 global-input 时，宿主将代码根目录、架构 path、执行器、runtime 等提取到项目 config；预算/门禁放入 defaults。整体规范路径可映射 requirements_path；已有整体用例可保存为项目用例文件并引用 test_cases_path。run_id/module_name/基线及生成产物不写项目配置。导入后仍由 Global 为本轮生成范围正确的规范和测试列表。

新宿主入口始终走本页流程，不能跳过上下文固化。

## 父子共同规划视野与知识资料

可选 knowledge_paths 是知识文档绝对路径数组，首次保存、增量更新/删除沿用配置版本协议；数组整体替换。prepare 把每份知识文档复制并绑定摘要到 source_refs.knowledge_paths，旧运行继续读取原快照。父 MO 与子 MO 都从步骤视图的 planning_context 读取完整 legacy_root/target_root、global_spec、new_architecture、project_context_ref/project_sources（包括规则与知识），以及最新父子分工/依赖。全局代码目录用于只读理解和复用检查；目标源码不是全文复制快照，实际代码变化仍受 baseline/锁/冻结约束。缺失必要知识或未声明公共能力 owner 时先记录问题，不能凭局部信息重复实现。

## 二方库/其他项目模块来源

新增可选 reuse_sources 数组，元素使用 [reuse-source.json](../../../template/reuse-source.json)：source_id、绝对 root、范围内 module_paths、description。目标项目 TARGET 自动作为来源；外部输入仍只读。init/update 保存并按数组替换规则更新，prepare 检查目录/模块可访问并将来源配置固化，旧运行不跟随新配置。prepared_input 输出 reuse_required=true；bind_run 从快照恢复来源，显式不匹配输入被拒绝。源码不全文快照，语义抽取及选中 provider/version 的内容证据另由 Agent 经 Ledger 记录；详见 [复用协议](reuse-dependencies.md)。

## 独立构建配置

可选 build 保存 argv/cwd/timeout_seconds/environment_ref，用户更新直接按原协议更新，prepare 固化命令与环境文档。没有指定命令时 GO 全目标搜索脚本、默认评估 Gradle assemble；宿主将旧 quality_gates.build_argv 迁入 build.argv。新输入 split_testing_required=true，不能通过缺自动化环境关闭编译门禁。详见 [构建与自动化协议](build-automation.md)。

## 跨运行经验沉淀与复用

跨 run 的分析/切分经验只经经验库抽象复用，不手工拷入新 Run：
1. **经验沉淀**：收尾审计/父汇总 ACK 从事件采集观察（切分/边界调整、重规划、修复模式、阻塞及解除依据、一次冻结改交计划或同因被拒达三次）；失败为 pending，可重试。配置 `experience_root`（绝对目录）则多工作区共用一库，块名 `<project_id>/<run_id>`。缺适用条件、根因、策略、结果或下次检查项的观察待 `/sdd-retrospect` 抽象，经 Ledger retrospect 或 run-review 的 lessons_ref 提交；harvest 只投影，不改业务状态。
2. **规划指导**：prepare 仅固化完整抽象经验，原始观察留存供复盘，不臆造根因。本 Run 的不可变 history_refs 纳入通用及关联叶子经验，预检绑定版本；失败/未验证策略辅助避错，已验证模式也不替代当前冻结/测试。
