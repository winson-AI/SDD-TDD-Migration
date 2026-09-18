# 项目上下文：初始化、更新与运行时固化

## 三层数据

1. 项目配置：跨运行复用的代码根目录、架构/需求/用例/规则文档路径、测试执行器、宿主配置和默认预算。模板 [project-context.json](../../../template/project-context.json) 是 `config` 内容。
2. 本次请求：run_id、entry_mode、module_name 和明确的临时 overrides。默认 project；single-module 只需模式和模块名，不能将本次模块选择保存成项目默认值。
3. 运行快照：启动时固定的项目版本、有效配置、文档副本和本次选择，供 Global 生成 SPEC/Testing list，并供下游持续读取。

自然语言解析、项目识别和真实 Agent 派发由宿主完成。[project_context.py](../../migration-ledger/scripts/project_context.py) 实际实现配置保存、增量更新、历史、快照与校验；它不生成业务 SPEC 或测试。

## 固定位置与身份

默认项目配置目录是 `<迁移工作目录>/.sdd-migration`，CLI `--root` 可显式指定。一个目录对应一个稳定 project_id；宿主先从当前项目定位目录，再读配置。多项目不能共用同一个配置文件；项目不明确时先定位，不套用其他项目上下文。配置目录独立于 legacy/target，目标路径更新不搬迁配置。

```text
<工作目录>/.sdd-migration/
  project-context.json           # 当前已提交记录：project_id/revision/config/来源
  history/<sha256>.json           # 不可变历史版本，previous_ref 串联
  sources/<sha256>.*             # 用户输入来源的副本
  .context.lock                  # 单写者文件锁
<run_root>/
  context/snapshot.json           # 本轮冻结上下文
  context/files/<sha256>.*        # 本轮架构、规则、来源等证据副本
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
  "source_ref": {"path": "/workspace/user-input/update-002.md", "sha256": "<实际摘要>"}
}
```

默认值存放在 config.defaults：entry_mode 固定 project；budgets、quality_gates、repair_policy 使用原有字段。test_adapter/runtime 与原 global-input 结构一致。配置只引用宿主环境或凭证名称，不在模板中放凭证值。

## 运行时固化

宿主先保存本次明确的项目更新，再调用 prepare：

1. 读取最新已提交项目版本；可用 run-request.expected_revision 指定必须匹配的版本。
2. 合并本次 overrides；读取 entry_mode/module_name，分配 run_id。验证目录、模式与配置。
3. 在独立 run_root 保存 snapshot.json，固定 project_id、project_revision、原配置摘要、有效配置、本次选择与用户来源；架构/需求/用例/规则和测试环境说明复制到本轮证据目录。JSON 来源按不透明文件保存，不能被误当作需要跟随内嵌路径的 Ledger 请求。
4. prepare 返回 project_context_ref 和 `input`，作为 Global 的分析输入；其中 global_spec/需求/CASE/PATH 待 Global 生成。宿主将 Global 完成的高层输入保存为 `<run_root>/input.json`，计算 input_ref，再构造原有 Ledger init 请求。未生成完整非空规范/用例前不得启动严格 init。
5. init payload 必须传 project_context_ref、input_ref、Global 生成的 global_spec/requirement_ids/case_ids/global_paths，以及快照对应的 legacy_root/target_root/new_architecture、entry_mode/module_name 和四项可执行预算。single_module_id 由 Global 生成，标识选定根功能；父 MO 随后拆分子功能，用户仍只输入模块名。预算取高层 input.budgets，摊平为低层字段。
6. Ledger 校验快照所属 run/root、路径、模式/模块名、架构引用及预算。运行状态保存 project_id/project_revision/project_context_ref；已有快照时不能漏传引用。后续事务和 status 校验冻结证据，禁止换用最新配置。

prepare 同一请求重试返回原快照，即使项目配置已经更新。相同 run_root 的新请求不能覆盖旧快照；初始化过的旧运行也不能后补快照伪造启动依据。prepare 的返回只代表上下文已固化，init ACK 才代表运行进入 Ledger。

配置更新只影响后续新运行。既有运行继续使用冻结版本；需要采用新配置时，由 Global 分析影响，使用新 run_id/run_root 准备运行，相关规格按原门禁重新澄清/冻结/复测，不能继承旧 Green 或把配置更新当作批准。本地本轮不提供活动运行的快照就地替换。

快照固定配置和引用文档；业务源码、执行器二进制及设备环境仍由已有 code baseline/测试执行回执验证，不声称复制了整个工程或设备环境。

## CLI

以下是实际 Python 命令；`/sdd-context`、`/sdd-init` 仍是宿主需接入的命令定义。配置目录参数指向 `.sdd-migration` 本身，run_root 与其分离。请求 JSON 由宿主根据真实用户输入整理。

```bash
package_root="/Users/winson/CodeBase/WF-Designer/SDD-TDD-Migration"
context_root="/workspace/migration/.sdd-migration"

python3 "$package_root/skills/migration-ledger/scripts/project_context.py" init \
  --root "$context_root" --request /workspace/context-init.json --host-context /workspace/host.json

python3 "$package_root/skills/migration-ledger/scripts/project_context.py" update \
  --root "$context_root" --request /workspace/context-update.json --host-context /workspace/host.json

python3 "$package_root/skills/migration-ledger/scripts/project_context.py" show --root "$context_root"
python3 "$package_root/skills/migration-ledger/scripts/project_context.py" history --root "$context_root"

python3 "$package_root/skills/migration-ledger/scripts/project_context.py" prepare \
  --root "$context_root" --run-root /workspace/migration/runs/login-v1 \
  --request /workspace/run-request.json --host-context /workspace/host.json
```

[run-request.json](../../../template/run-request.json) 中的元数据、项目标识、来源引用由宿主生成；用户的单模块选择仍只有 `single-module + 功能模块名`。

## 现有 global-input 兼容

新入口先初始化/更新项目配置再 prepare。用户提供旧 global-input 时，宿主将代码根目录、架构 path、执行器、runtime 等提取到项目 config；预算/门禁/修复策略放入 defaults。整体规范路径可映射 requirements_path；已有整体用例可保存为项目用例文件并引用 test_cases_path。run_id/module_name/基线及生成产物不写项目配置。导入后仍由 Global 为本轮生成范围正确的规范和测试列表。

旧 Ledger 运行没有 project_context_ref 时按旧协议继续，不伪造历史快照；旧直接 init 在没有预备快照时仍兼容。新宿主入口应始终走本页流程，不能以兼容路径跳过上下文固化。

## 父子共同规划视野与知识资料

可选 knowledge_paths 是知识文档绝对路径数组，首次保存、增量更新/删除沿用配置版本协议；数组整体替换。prepare 把每份知识文档复制并绑定摘要到 source_refs.knowledge_paths，旧运行继续读取原快照。父 MO 与子 MO 都从 status.planning_context 读取完整 legacy_root/target_root、global_spec、new_architecture、project_context_ref/project_sources（包括规则与知识），以及最新父子分工/依赖。全局代码目录用于只读理解和复用检查；目标源码不是全文复制快照，实际代码变化仍受 baseline/锁/冻结约束。缺失必要知识或未声明公共能力 owner 时先记录问题，不能凭局部信息重复实现。

## 二方库/其他项目模块来源

新增可选 reuse_sources 数组，元素使用 [reuse-source.json](../../../template/reuse-source.json)：source_id、绝对 root、范围内 module_paths、description。目标项目 TARGET 自动作为来源；外部输入仍只读。init/update 保存并按数组替换规则更新，prepare 检查目录/模块可访问并将来源配置固化，旧运行不跟随新配置。prepared_input 输出 reuse_required=true；bind_run 从快照恢复来源，显式不匹配输入被拒绝。源码不全文快照，语义抽取及选中 provider/version 的内容证据另由 Agent 经 Ledger 记录；详见 [复用协议](reuse-dependencies.md)。
