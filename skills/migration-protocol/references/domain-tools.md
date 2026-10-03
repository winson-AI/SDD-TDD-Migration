# 领域工具受限接入

领域工具提供 UI 源码抽取、截图证据校验、精确资源转换、视觉比较及 Foundation 知识；宿主按下表开放受限操作，GO/MO、Ledger、冻结、修复预算和独立审计仍按 SDD 协议执行。外部全流程技能含设计、改码、提交或返工控制，整包执行会跨越 SDD 角色权限，不作为任何角色的执行规约加载。

## 总则

证据契约只有当前一套，prepare 与 Ledger init 均按其校验。UI fidelity 默认值及适用条件以本轮快照为准；开启时 applicable UI 必须有模型/源树/目标覆盖，不是可选附录。领域工具只按本协议使用：Spec-Designer 分析 UI，Implementer 精确迁移资源并接线，Test-Runner 构建/功能测试/视觉取证，Fixer 修复，Auditor 独立；不得加载完整的外部实现或对齐技能来合并这些权限。原始结果引用、转换证据及正式 payload 均在本轮受管目录留存并经 Ledger 提交。仅自动化不可用仍按 Yellow 缺测收尾，不阻止独立任务。

## 角色与权限

| SDD 角色 | 领域操作 | 产出与边界 |
| --- | --- | --- |
| Spec-Designer | `analyze-ui`、`validate-ui`、`render-reference`、知识查询与 Foundation 解析 | 源索引、运行时索引、合并 UI 树、范围与资源闭包进入规划；只生成分析工件，不改目标源码或资源 |
| Implementer | `resource-convert`，消费已冻结 UI/资源证据 | 在当前 assignment 与写范围内完成精确资源转换及真实消费者接线；不改 SPEC/tasks/验收，不作正式通过判断 |
| Test-Runner | 正式构建走 `execute_test.py`；视觉使用 `compare-only`、`image-parity` | 读取当前代码/基线生成比较评分；结合独立设备交互、语义比较和正式执行回执提交三态，不修源码、资源、构建配置或 SPEC |
| Fixer | 经 Ledger 授权的实现/资源修复，可用 `resource-convert` | 沿原修复预算和写范围提交补丁；行为或验收变更先提 CR；自测不能代替正式复测 |
| Auditor | 独立审阅，按审计 assignment 只读比较与复测 | 不兼实现者、修复者或本轮测试脚本作者；按当前基线裁决，不能在比较过程中改码 |
| Diagnostician | 知识查询、基于真实日志的 `knowledge-diagnose` | 命中项是候选原因，结合当前源码/执行证据判定根因；不修复或扩权 |
| Host / GO / MO | 真实派发、身份注入、上下文与 assignment 绑定、结果路由 | 只通过 Ledger 推进；工具返回不直接修改模块状态或自动增加修复轮次 |

`import-evidence` 只转换当前角色获准读取的已有产物。完整技能中的设备遍历、自动修 UI、提交 Git、重建 OpenSpec 或独立循环，不因调用其脚本而获得授权。设备 Capture 仍由宿主按已声明 page/state/coverage 与设备权限执行，不能把源码分析当成截图成功。

## 接入与证据流

受限入口为 [lean_worker.py](../../migration-ledger/scripts/lean_worker.py)。宿主传认证过的 host-context、module_id 和执行阶段 assignment；请求只选择白名单操作及工具参数，不接受任意 shell 或任意 skill。角色身份和受管路径检查不等于操作系统沙箱，外部工具仍受宿主实际文件/设备权限约束。

```sh
python3 <package>/skills/migration-ledger/scripts/lean_worker.py \
  --root <run_root> --request <staged-request.json> --host-context <host.json>
```

请求示例见 [domain-worker-request.json](../../../template/domain-worker-request.json)。operation/request_id/module_id/args 由宿主组装；resource-convert/compare-only 还须绑定当前 assignment_id/fencing_token。输出位置由入口固定推导，不提供任意 output_dir。host-context 由宿主认证注入，不能让 worker 自选身份。

| operation | args 要点 | 当前实际能力 |
| --- | --- | --- |
| `analyze-ui` | entry/source_files/layouts，选填 capture_ref、targets、manifests、image_sinks | 从固定 legacy_root 收集源索引（含图片信号，见 [图片与图标对齐](ui-fidelity.md#图片与图标对齐)）；有合法 Capture 时选择运行时索引。Spec-Designer 据此生成 UI 树，再 validate-ui；不自动证明源闭包完整 |
| `validate-ui` | ui_tree_ref/source_index_ref/runtime_index_ref，选填 resource_scope | 校验树与原始索引一致；source-only 不伪造 runtime_index_ref；resource_scope 仅说明有证据的范围外变体 |
| `resource-scan` | 选填 source_index_ref/ui_tree_ref/extra_refs | 只读查找当前闭包资源，输出候选文件及 hash，保留 base/night/语言等源变体；给出树与索引时另附按记录预填的 skeletons；不写目标、不作精确性裁决 |
| `render-reference` | source_index_ref/source_resource/qualifier | 把索引内的存量资源文件离线渲染为参考栅格（reference.png/json），绑定文件 SHA；Spec-Designer/Test-Runner/Auditor 可用，随声明它的 image_checks 冻结 |
| `image-parity` | path_id/manifest_ref/round，需 assignment | 对已完成的候选 capture，按冻结的 image_checks 在目标 view tree 定位节点、裁剪并比较，写 image-parity.json 与裁剪图；只是测量，Ledger 验收时重算；Test-Runner/Auditor 可用 |
| `resource-convert` | task_id/resource_item_id + source/destination/source_id/target_ref/consumer，选填 resolve_ref/consumer_tint | 在冻结任务范围内执行 exact_vector_xml、byte_copy 或单项 value_xml_exact；参数必须与冻结资源映射一致，其余策略仍由 Implementer/Fixer 按 SPEC 实现 |
| `compare-only` | reference_ref/candidate_ref | 生成确定性 score；score 是证据，不等于 ALIGNED，不操作设备、不自动修 UI、不生成手势执行事实 |
| `visual-install` / `visual-capture` / `semantic-inspect` | 当前 PATH/assignment、冻结 visual_execution、构建/装机/比较引用 | 受限设备安装、捕获与语义比较，详见 [视觉执行](visual-execution.md)；只产出证据，不写 Ledger、不修源码 |
| `import-evidence` | kind/source_ref；UI 另给 target/ui_tree_ref/source_index_ref/runtime_index_ref，选填 resource_scope | 转换 ui/alignment/validation/foundation/resource 原始结果；资源导入另绑定 approved_spec_hash。导入结果不提升角色权限、不自动验收 |
| `knowledge-query` | mode 为 topics/topic/foundation/external；topic 用 topic_id；foundation/external 用 query，可选 full(bool) | 查询 bundled 索引、主题、Foundation 或 Harmony 外部能力候选，保留 index/catalog/record/topic/cookbook 引用与 hash；不加载完整的外部技能 |
| `knowledge-diagnose` | error_ref（path/sha256） | 读取真实日志片段，按原工具 pattern 匹配候选原因和 cookbook；不作根因裁决 |
| `foundation-resolve` | requirements（非空字符串数组）；或 requirements=[] 且 no_new_dependencies=true | 在 bundled catalog 内解析目标敏感依赖及版本；不修改目标、不联网解依赖。result.json 可作 plan.dependency_resolution_ref |
| `foundation-verify` | resolution_ref、catalog_ref（均 path/sha256） | resolution 必须在本 run；catalog 必须是快照 target_root 内的实际 TOML，核对坐标版本并留证；不代替 build |

### 知识操作权限与例子

四个知识操作需要合法宿主 principal 与有效运行快照，均只读、不要求 assignment；规划和失败分析阶段也可调用。knowledge-query 对 GO/MO/Spec-Designer/Implementer/Fixer/Diagnostician/Test-Runner/Auditor/Escalation 开放；knowledge-diagnose 对 Implementer/Diagnostician/Fixer/Test-Runner/Auditor 开放；foundation-resolve 只给 GO/MO/Spec-Designer；foundation-verify 给 Implementer/Fixer/Test-Runner/Auditor。Ledger 角色不承担领域读取。Host 认证后用对应角色运行，不让 worker 自选身份。

请求使用同一个 lean_worker CLI，最小主题查询见 [knowledge-request.json](../../../template/knowledge-request.json)。其余 args 示例：

```json
{"mode":"topics"}
{"mode":"foundation","query":"ktor","full":false}
{"mode":"external","query":"webrtc","full":false}
{"error_ref":{"path":"<真实错误片段绝对路径>","sha256":"<实际摘要>"}}
{"requirements":["io.ktor:ktor-client-curl"],"no_new_dependencies":false}
{"requirements":[],"no_new_dependencies":true}
{"resolution_ref":{"path":"<run>/staging/<spec>/<request>/result.json","sha256":"<实际摘要>"},"catalog_ref":{"path":"<target>/gradle/libs.versions.toml","sha256":"<实际摘要>"}}
```

以上每行分别用于相应 operation 的 args，名称/坐标由当前目录查询结果确定，不能照抄成项目事实。每次调用的 request/result/receipt 都写入 `staging/<actor>/<request_id>`；查询到的知识引用保留 hash。角色仍需把相关结果随原上下文、plan、实现或测试提交，工具不会提交 Ledger 或自动触发下一角色。Foundation 配置唯一入口、默认关闭及不适用处理见 [工程纪律](engineering-disciplines.md)。

知识结果附 `sdd_adaptation_ref`，将上游平台决策/实现/验证概念映射到本轮四维分析、冻结 SPEC、task_trace/dimension_evidence 及正式 PATH/ASSERT。`external` 查询只返回目录快照候选，所列历史版本/verified 标记不代表当前目标已验证；无匹配也不能据此判定无法实现。上游独立 probe 未接入，结果明确 `probe_support:not-supported`，由当前角色在已有任务和测试路径中设计并验证所选方案；不安装包、不运行目录里的命令、不创建 `.a2c` 或独立状态文件。

正式 visual PATH 使用已有 execute_test 的 adapter/host receipt 通道，不能把直接 compare-only 或视觉辅助工具的 receipt 当作正式测试回执。[视觉执行工具](visual-execution.md) 可生成装机/Capture/语义证据；手势仍需其实际执行证据，未配置相关运行器时记录缺口。

入口及查询/诊断/resolve 使用 Python 3.10+；`foundation-verify` 单项需要 Python 3.11+ 的 tomllib，缺少时明确拒绝并保留原因。`compare-only`、`image-parity`、`render-reference` 还需要 Pillow（矢量 drawable 的渲染另需 `rsvg-convert`），可使用本 run 已准备好的 Harmony sandbox 环境。缺少时保留原因（compare-only 为 `comparison-unavailable`），由 Test-Runner 按现有 Yellow/未执行通道处理，不自动安装依赖或阻止其他模块。

使用 [visual-test-adapter.json](../../../template/visual-test-adapter.json) 实例化 adapter JSON，其 argv 指向 [lean_visual_adapter.py](../../migration-ledger/scripts/lean_visual_adapter.py)、当前原始 alignment 文件与 target_root。有冻结手势才在 argv 添加 `--interaction <id>`（可重复）；带 `image_check_ids` 的 PATH 添加 `--image-parity <报告>`，无 `baseline_ref` 时可省略 `--alignment`。宿主取得 visual assignment 后执行：

```sh
python3 <package>/skills/migration-ledger/scripts/execute_test.py \
  --root <run_root> --module M001 --assignment <assignment-id> \
  --path-id VISUAL-M001-001 --adapter <adapter.json> --cwd <target_root> \
  --output <run_root>/runs/harmony/automation/<new-attempt>
```

execute_test 自动传 query/result 文件并保存正式回执，adapter 只重验与转换独立比较产物，不捕获截图、修复代码或发明视觉 verdict。当前 adapter 仅支持冻结 `expected: true` 的布尔视觉对齐断言；其他断言类型用项目已有适配器。声明手势时 query 带冻结模型的完整 frozen_interaction，proof.required_interaction 及实际 action/observed 都要与它相符，不能只对 ID 和 PASSED。Green 的 HAP 必须属于当前模块已接受 build_artifacts，构建执行器从本次 runner 收集产物；旧 HAP 即使文件 hash 仍匹配也不能替代本轮构建。

每次调用保留三个层次：

1. 原始输入/输出引用及实际 hash，包括 Capture manifest、源索引、UI 树、资源映射、比较结果与日志；外部来源只读，不改写旧 hash。
2. [lean_adapter.py](../../migration-ledger/scripts/lean_adapter.py) 转换出的 SDD 证据，并保留对原始结果的引用。结构转换不代表命令执行、语义一致、视觉通过或真实派发。
3. 角色提交的正式 payload，绑定 freeze/assignment、TASK/PATH/ASSERT、当前代码与构建产物，经 `submit`/`accept` 或审计事件进入 Ledger。角色返回文本和 worker 成功退出都不能替代这些事件。

一般工具产物写入本 run 的 `staging/<actor>/<request_id>`；截图与视觉辅助产物写入 `runs/harmony/sandbox/<actor>/<request_id>`。正式构建与自动化仍使用既有 `runs/build/<attempt>`、`runs/harmony/automation/<attempt>`。新请求使用新目录；不写回技能包、输入旁、目标仓 `.a2c` 或任意 cwd。提交后以下游收到的 Ledger 工件引用为准，详见 [留存布局](storage-layout.md)。

## 产物转换

| 原始产物 | SDD 接入目标 | 验收责任 |
| --- | --- | --- |
| schema 2 Capture manifest + source/runtime 索引 + UI 树 | UI item 的 `semantic_model.ui_evidence`、目标覆盖与冻结基线 | Spec-Designer 提交，MO 冻结；COMPLETE 与显式 SOURCE_ONLY 分开 |
| 精确 `resourceMappings` | Resource item 的源/目标/消费者证据与 task trace | Implementer/Fixer 提交，MO 接受，正式 Testing 验证消费者 |
| compile/test/package checks 与 HAP/HSP | 对应冻结 build/automation PATH 的结果与当前产物引用 | Test-Runner 经正式执行器留证；不能把导入的 `passed` 当作本轮执行 |
| 逐目标 alignment 与 interaction checks | visual PATH 的三态、节点差异、同目标/当前 HAP/当前代码基线的证据 | Test-Runner 只读比较，失败交 Fixer，Auditor 独立裁决 |

每个 runtime UI 目标都有自己的 visual PATH，不能用一条结果或历史 HAP 的 ALIGNED 覆盖另一状态或当前版本；source-only 保留缺少视觉实证的结论。完整字段见 [UI 保真控制道](ui-fidelity.md)。

### 资源执行与事实绑定

资源扫描对 GO/MO/Spec-Designer/Implementer/Fixer/Test-Runner/Auditor 开放，只读候选索引与源码。转换仅允许 Implementer/Fixer；请求例子见 [resource-request.json](../../../template/resource-request.json)。写入前校验活动 assignment、freeze、fencing token、模块与 task.scope.write_paths、dimension_trace 的任务所有权，以及冻结 source_resource_ref/目标路径/访问器/消费者/精确策略。扫描发现多个配置变体时，Spec 分别记录，不自动任选一个。

冻结中，声明精确策略的资源项必须给出 source_resource_ref（真实源文件 path/sha256）、Android source_resource（如 @string/title）和 qualifier（base 或源 res 目录后缀），并从文件/values 条目核对 resource_kind、nine_patch、source_unit。每个源 ID + qualifier 对应一个 Resource item，别名与附加资源各带源事实。consumer 与 consumer_refs 的对应见 [精确性纪律](ui-fidelity.md#精确性纪律)。闭包、变体、范围外排除、平台资源与旧索引的规则见 [精确性纪律](ui-fidelity.md#精确性纪律)。

未知真实资源类型保留原始类型/hash，选 blocked 或带适配审查证据的 manual_exact；自动转换白名单不因此扩大，blocked 仍不能 Green，资源转换也不执行 blocked 策略。无法获取源文件时保留 blocked + blocked_reason 的显式缺口，不为填模板伪造 source_resource_ref 或篡改 resource_kind。

源目标 qualifier 不同须冻结 configuration_mapping，包含 source_qualifier、target_qualifier（代码路由用 code）、scope.configurations/reason 和 evidence_refs。限定 night 的模块可以有据映射到 base；范围包含多个配置时另给 consumer_condition.expression/consumers。多个源变体共用目标文件必须给不同的真实消费者条件；语义正确性由 MO 审阅和测试验证，非空表达式本身不能证明分支正确。源目标相同 qualifier、普通 base 到代码常量路由无需空配置。配置证据 hash 持续校验，转换结果保留 configurationMapping。

byte_copy 要求源目标字节一致；value_xml_exact 仅自动迁移一个 string/plurals/string-array/integer-array 条目，保留结构，目标已有不同内容或未解析引用则拒绝覆盖、交给现有修复/变更流程。向量的 resolve_ref/consumer_tint 也须冻结。输出仍是 staged 工件与 task trace，不代表生产消费者已验证。资源导入以 sourceId + qualifier 区分变体；重复同配置映射、伪造类型或不同字节的 byte_copy 被拒绝。

## 证据保留与修复闭环

证据契约要求目标覆盖、原始引用和资源闭包，但不改变 GO/MO/审计权责；已提交证据不重算或改写。

视觉差异进入原有 Red→诊断→Fixer→正式复测闭环，不启用外部工具自带的额外修复循环或自动重置预算。仅自动化环境不可用时，automation/visual 留 Yellow/未执行，沿既有 `automation-unavailable`、`completed-with-unverified-tests` 规则收尾，独立任务和可用构建下游继续；不得伪 Green，也不强迫用户为纯缺测恢复环境。

知识工具执行、可选冻结 gate、依赖决策阶梯、澄清与 Git 纪律见 [工程纪律](engineering-disciplines.md)。领域工具不自动选择主题、执行修复或创建另一套调度器；GO/MO/Ledger 仍是原控制流。这些接入机制提供结构和权限约束；真实宿主派发、实际构建/设备执行及行为保真仍需对应的独立执行证据，不能由 `/sdd-verify` 或转换器单独证明。
