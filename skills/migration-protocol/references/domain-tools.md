# 领域工具受限接入

领域工具提供 UI 源码抽取、截图证据校验、精确资源转换、视觉比较及 Foundation 知识；宿主按下表开放受限操作，GO/MO、Ledger、冻结、修复预算和独立审计仍按 SDD 协议执行。

## 总则

applicable UI 必须有模型/源树/目标覆盖，不是可选附录。领域工具只按本协议使用：Spec-Designer 分析 UI，Implementer 精确迁移资源并接线，Test-Runner 构建/功能测试/视觉取证，Fixer 修复，Auditor 独立；不得加载完整的外部实现或对齐技能来合并这些权限。原始结果引用、转换证据及正式 payload 均在本轮受管目录留存并经 Ledger 提交。仅自动化不可用仍按 Yellow 缺测收尾，不阻止独立任务。

## 角色与权限

| SDD 角色 | 领域操作 | 产出与边界 |
| --- | --- | --- |
| Spec-Designer | `analyze-ui`、`validate-ui`、`resource-plan`、`screen-checks`、`render-reference`、知识查询与 Foundation 解析 | 源索引、运行时索引、合并 UI 树、范围与资源闭包进入规划；只生成分析工件，不改目标源码或资源 |
| Implementer | `resource-sync`、`resource-convert`，消费已冻结 UI/资源证据 | 在当前 assignment 与写范围内完成精确资源转换及真实消费者接线；不改 SPEC/tasks/验收，不作正式通过判断 |
| Test-Runner | 正式构建走 `execute_test.py`；视觉使用 `compare-only`、`image-parity` | 读取当前代码/基线生成比较评分；结合独立设备交互、语义比较和正式执行回执提交三态，不修源码、资源、构建配置或 SPEC |
| Fixer | 经 Ledger 授权的实现/资源修复，可用 `resource-convert` | 沿原修复预算和写范围提交补丁；行为或验收变更先提 CR；自测不能代替正式复测 |
| Auditor | 独立审阅，按审计 assignment 只读比较与复测 | 不兼实现者、修复者或本轮测试脚本作者；按当前基线裁决，不能在比较过程中改码 |
| Diagnostician | 知识查询、基于真实日志的 `knowledge-diagnose` | 命中项是候选原因，结合当前源码/执行证据判定根因；不修复或扩权 |
| Host / GO / MO | 真实派发、身份注入、上下文与 assignment 绑定、结果路由 | 只通过 Ledger 推进；工具返回不直接修改模块状态或自动增加修复轮次 |

`import-evidence` 只转换当前角色获准读取的已有产物。完整技能中的设备遍历、自动修 UI、提交 Git、重建 OpenSpec 或独立循环，不因调用其脚本而获得授权；源码分析不等于截图成功。

## 接入与证据流

受限入口为 [lean_worker.py](../../migration-ledger/scripts/lean_worker.py)。宿主传认证过的 host-context、module_id 和执行阶段 assignment；请求只选择白名单操作及工具参数，不接受任意 shell 或任意 skill。角色身份和受管路径检查不等于操作系统沙箱，外部工具仍受宿主实际文件/设备权限约束。

```sh
python3 <package>/skills/migration-ledger/scripts/lean_worker.py \
  --root <run_root> --request <staged-request.json> --host-context <host.json>
```

请求示例见 [domain-worker-request.json](../../../template/domain-worker-request.json)。operation/request_id/module_id/args 由宿主组装；写目标、比较与设备操作还须绑定当前 assignment_id/fencing_token。输出位置由入口固定推导，不提供任意 output_dir；worker 不能自选身份。

| operation | args 要点 | 当前实际能力 |
| --- | --- | --- |
| `analyze-ui` | entry/source_files/layouts，选填 capture_ref、targets、manifests、image_sinks、layout_helpers | 从固定 legacy_root 收集源索引（含使用点、图片来源与参数，见 [搬运](resource-transfer.md#使用点与闭包)）；有合法 Capture 时选择运行时索引。Spec-Designer 据此生成 UI 树，再 validate-ui；不自动证明源闭包完整 |
| `validate-ui` | ui_tree_ref/source_index_ref/runtime_index_ref，选填 resource_scope | 校验树与原始索引一致；source-only 不伪造 runtime_index_ref；resource_scope 仅说明有证据的范围外变体 |
| `resource-scan` | 选填 source_index_ref/ui_tree_ref/extra_refs | 只读查找当前闭包资源，输出候选文件及 hash，保留 base/night/语言等源变体；给出树与索引时另附按记录预填的 skeletons；不写目标、不作精确性裁决 |
| `resource-plan` | dimension_analysis_ref | 派生模块的参数表与复制清单（项目声明了约定时），并列出待登记的资源、未声明的使用点、待映射的 token 与待定值的 expression；MO 可用 |
| `resource-sync` | task_id，需 assignment | 在该任务写范围内按冻结清单复制文件、按参数表写出参数文件；不覆盖内容不同的已有文件；Fixer 可用 |
| `screen-checks` | dimension_analysis_ref | 为尚无检查的图片使用点派生 image 检查并渲染参考，附文本检查建议，渲染不了的列入 unrendered；MO 可用 |
| `render-reference` | source_index_ref/source_resource/qualifier | 把索引内的存量资源文件离线渲染为参考栅格（reference.png/json），绑定文件 SHA；Spec-Designer/Test-Runner/Auditor 可用，随声明它的 image_checks 冻结 |
| `resource-convert` | task_id/resource_item_id + source/destination/source_id/target_ref/consumer，选填 resolve_ref/consumer_tint | 在冻结任务范围内执行 exact_vector_xml、byte_copy 或单项 value_xml_exact；参数必须与冻结资源映射一致，其余策略仍由 Implementer/Fixer 按 SPEC 实现 |
| `visual-install` / `visual-capture` / `compare-only` / `semantic-inspect` / `image-parity` | 当前 PATH/assignment、冻结 visual_execution、构建/装机/比较引用 | 受限设备安装、捕获、确定性评分、语义比较与图像检查测量，详见 [视觉执行](visual-execution.md#2-执行节点)；只产出证据（score 不等于 ALIGNED），不写 Ledger、不自动修 UI、不生成手势执行事实 |
| `import-evidence` | kind/source_ref；UI 另给 target/ui_tree_ref/source_index_ref/runtime_index_ref，选填 resource_scope | 转换 ui/alignment/validation/foundation/resource 原始结果；资源导入另绑定 approved_spec_hash。导入结果不提升角色权限、不自动验收 |
| `knowledge-query` | mode 为 topics/topic/foundation/external；topic 用 topic_id；foundation/external 用 query，可选 full(bool) | 查询 bundled 索引、主题、Foundation 或 Harmony 外部能力候选，保留 index/catalog/record/topic/cookbook 引用与 hash；不加载完整的外部技能 |
| `knowledge-diagnose` | error_ref（path/sha256） | 读取真实日志片段，按原工具 pattern 匹配候选原因和 cookbook；不作根因裁决 |
| `foundation-resolve` | requirements（非空字符串数组）；或 requirements=[] 且 no_new_dependencies=true | 在 bundled catalog 内解析目标敏感依赖及版本；不修改目标、不联网解依赖。result.json 可作 plan.dependency_resolution_ref |
| `foundation-verify` | resolution_ref、catalog_ref（均 path/sha256） | resolution 必须在本 run；catalog 必须是快照 target_root 内的实际 TOML，核对坐标版本并留证；不代替 build |

### 知识操作权限与例子

四个知识操作需要合法宿主 principal 与有效运行快照，均只读、不要求 assignment；规划和失败分析阶段也可调用。knowledge-query 对 GO/MO/Spec-Designer/Implementer/Fixer/Diagnostician/Test-Runner/Auditor/Escalation 开放；knowledge-diagnose 对 Implementer/Diagnostician/Fixer/Test-Runner/Auditor 开放；foundation-resolve 只给 GO/MO/Spec-Designer；foundation-verify 给 Implementer/Fixer/Test-Runner/Auditor。Ledger 角色不承担领域读取。

请求使用同一个 lean_worker CLI，各操作的 args 示例见 [knowledge-request.json](../../../template/knowledge-request.json)；名称与坐标由当前目录查询结果确定，不能照抄成项目事实；查询到的知识引用保留 hash，由角色随原上下文、plan、实现或测试提交。Foundation 配置唯一入口、默认关闭及不适用处理见 [工程纪律](engineering-disciplines.md)。

知识结果附 `sdd_adaptation_ref`，将上游平台决策/实现/验证概念映射到本轮四维分析、冻结 SPEC、task_trace/dimension_evidence 及正式 PATH/ASSERT。`external` 查询只返回目录快照候选，所列历史版本/verified 标记不代表当前目标已验证；无匹配也不能据此判定无法实现。上游独立 probe 未接入，结果明确 `probe_support:not-supported`，由当前角色在已有任务和测试路径中设计并验证所选方案；不安装包、不运行目录里的命令、不创建 `.a2c` 或独立状态文件。

正式 visual PATH 使用已有 execute_test 的 adapter/host receipt 通道，不能把直接 compare-only 或 [视觉执行工具](visual-execution.md) 的 receipt 当作正式测试回执。

入口及查询/诊断/resolve 使用 Python 3.10+；`foundation-verify` 单项需要 Python 3.11+ 的 tomllib，缺少时明确拒绝并保留原因。`compare-only`、`image-parity`、`render-reference`、`screen-checks` 还需要 Pillow（矢量 drawable 的渲染另需 `rsvg-convert`），可使用本 run 已准备好的 Harmony sandbox 环境。缺少时保留原因（compare-only 为 `comparison-unavailable`），由 Test-Runner 按现有 Yellow/未执行通道处理，不自动安装依赖或阻止其他模块。

使用 [visual-test-adapter.json](../../../template/visual-test-adapter.json) 实例化 adapter JSON，其 argv 指向 [lean_visual_adapter.py](../../migration-ledger/scripts/lean_visual_adapter.py)、当前原始 alignment 文件与 target_root。有冻结手势才在 argv 添加 `--interaction <id>`（可重复）；带 `image_check_ids` 的 PATH 添加 `--image-parity <报告>`，无 `baseline_ref` 时可省略 `--alignment`。宿主取得 visual assignment 后执行：

```sh
python3 <package>/skills/migration-ledger/scripts/execute_test.py \
  --root <run_root> --module M001 --assignment <assignment-id> \
  --path-id VISUAL-M001-001 --adapter <adapter.json> --cwd <target_root> \
  --output <run_root>/runs/harmony/automation/<new-attempt>
```

execute_test 自动传 query/result 文件并保存正式回执，adapter 只重验与转换独立比较产物，不捕获截图、修复代码或发明视觉 verdict。当前 adapter 仅支持冻结 `expected: true` 的布尔视觉对齐断言；其他断言类型用项目已有适配器。手势与当前 HAP 的正式核对见 [视觉对齐](ui-fidelity.md#视觉对齐--automation-第二层不是独立阶段)。

每次调用保留三层：原始输入/输出引用及实际 hash（Capture manifest、源索引、UI 树、资源映射、比较结果与日志；外部来源只读，不改写旧 hash）；[lean_adapter.py](../../migration-ledger/scripts/lean_adapter.py) 转换出的 SDD 证据（保留对原始结果的引用，结构转换不代表命令执行、语义一致、视觉通过或真实派发）；角色经 `submit`/`accept` 或审计事件提交的正式 payload（绑定 freeze/assignment、TASK/PATH/ASSERT、当前代码与构建产物），角色返回文本和 worker 成功退出都不能替代这些事件。

工具产物写入本 run 的 `staging/<actor>/<request_id>`，截图与视觉辅助产物写入 `runs/harmony/sandbox/<actor>/<request_id>`，新请求用新目录；不写回技能包、输入旁、目标仓 `.a2c` 或任意 cwd，详见 [留存布局](storage-layout.md)。

## 产物转换

| 原始产物 | SDD 接入目标 | 验收责任 |
| --- | --- | --- |
| schema 2 Capture manifest + source/runtime 索引 + UI 树 | UI item 的 `semantic_model.ui_evidence`、目标覆盖与冻结基线 | Spec-Designer 提交，MO 冻结；COMPLETE 与显式 SOURCE_ONLY 分开 |
| 精确 `resourceMappings` | Resource item 的源/目标/消费者证据与 task trace | Implementer/Fixer 提交，MO 接受，正式 Testing 验证消费者 |
| compile/test/package checks 与 HAP/HSP | 对应冻结 build/automation PATH 的结果与当前产物引用 | Test-Runner 经正式执行器留证；不能把导入的 `passed` 当作本轮执行 |
| 逐目标 alignment 与 interaction checks | visual PATH 的三态、节点差异、同目标/当前 HAP/当前代码基线的证据 | Test-Runner 只读比较，失败交 Fixer，Auditor 独立裁决 |

各目标的 visual PATH 与完整字段见 [UI 保真控制道](ui-fidelity.md#视觉对齐--automation-第二层不是独立阶段)。

### 资源执行与事实绑定

复制清单、参数表与 `resource-sync` 的规则见 [资源与参数的搬运](resource-transfer.md#文件资源按路径复制)；本节是清单之外逐项登记的资源。资源扫描对 GO/MO/Spec-Designer/Implementer/Fixer/Test-Runner/Auditor 开放，只读候选索引与源码；发现多个配置变体时 Spec 分别记录。转换仅允许 Implementer/Fixer（请求见 [resource-request.json](../../../template/resource-request.json)）：写入前校验活动 assignment、freeze、fencing token、模块与 task.scope.write_paths、dimension_trace 的任务所有权，以及冻结的 source_resource_ref/目标路径/accessor/消费者/策略。item 的源事实、闭包、变体与平台资源见 [精确性纪律](ui-fidelity.md#精确性纪律)。

未知真实资源类型保留原始类型/hash，自动转换白名单不因此扩大。无法获取源文件时保留 blocked + blocked_reason，不伪造 source_resource_ref 或篡改 resource_kind。

源目标 qualifier 不同（密度与平台版本不算）须冻结 configuration_mapping：source_qualifier、target_qualifier（代码路由用 code）、scope.configurations/reason 和 evidence_refs。限定 night 的模块可有据映射到 base；范围含多个配置时另给 consumer_condition.expression/consumers，多个源变体共用目标文件须给不同的真实消费者条件。条件的语义由 MO 审阅和测试验证；相同 qualifier 与 base 到代码常量的路由无需配置。

`value_xml_exact` 只自动迁移一个 string/plurals/string-array/integer-array 条目并保留结构；目标已有不同内容或含未解析引用时拒绝覆盖，交给修复/变更流程。向量的 resolve_ref/consumer_tint 也须冻结。资源导入以 sourceId + qualifier 区分变体；重复映射、伪造类型或字节不同的 byte_copy 被拒绝。

## 证据保留与修复闭环

已提交证据不重算或改写。视觉差异进入原有 Red→诊断→Fixer→正式复测闭环，不启用外部工具自带的修复循环或自动重置预算。知识工具、依赖决策阶梯、澄清与 Git 纪律见 [工程纪律](engineering-disciplines.md)。领域工具不选择主题、不执行修复、不另建调度器；真实宿主派发、构建/设备执行与行为保真仍需各自的执行证据，不能由 `/sdd-verify` 或转换器单独证明。
