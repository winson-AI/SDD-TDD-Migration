# 模板实例化索引

所有 `{{...}}` 均为待填字段，不代表真实运行值。实例化后必须消除占位符；初始 pending/null/untested 保持真实状态，不得为模板完整而改成通过。缺失输入进入澄清，不能随意填入。

| 模板 | 作者及用途 |
| --- | --- |
| [global-input.json](global-input.json) | Global 从固定项目上下文生成本轮输入；宿主保存 input.json，Ledger 绑定引用及快照 |
| [module-input.json](module-input.json) | Global 生成功能切片输入，Ledger 写 modules/Mxxx/_input.json |
| [global-ledger.json](global-ledger.json) | Ledger 维护全局缓存；不得当事实日志直接修改 |
| [assignment.json](assignment.json) | 宿主身份绑定的单次任务；Ledger 创建 |
| [event.json](event.json) | 入站事件信封；Ledger 补服务端事件 ID/sequence/time |
| [proposal.md](proposal.md) | Spec-Designer：六件套 proposal |
| [spec.md](spec.md) | Spec-Designer：实例化为 specs/<capability>/spec.md 的 delta |
| [design.md](design.md) | Spec-Designer：旧→新架构与测试设计 |
| [tasks.md](tasks.md) | Spec-Designer 定义计划；Ledger 投影完成进度 |
| [status.md](status.md) | MO 决策，Ledger 将其中 JSON 同步为 modules/Mxxx.json 与 status.md |
| [checklist.md](checklist.md) | 冻结定义与 DoD 定义；Ledger 更新证据 |
| [freeze.json](freeze.json) | Spec-Designer 提案、Human/MO 审核、Ledger 接受 |
| [test-paths.json](test-paths.json) | Test-Runner：冻结前路径设计；实现后脚本绑定 |
| [test-design-input.json](test-design-input.json) / [test-design-result.json](test-design-result.json) | 编码前独立设计输入/结果；MO 接受后 plan.test_design_ref 绑定 |
| [test-result.json](test-result.json) | Test-Runner/Auditor 记录实际执行；Fixer 自测标明 producer |
| [implementation.md](implementation.md) | Implementer/Fixer：提交与 tasks 追溯、回归、回滚 |
| [diagnosis.md](diagnosis.md) | Diagnostician：只读根因报告 |
| [change-request.md](change-request.md) | Fixer 提建议；Spec-Designer/MO 审核 |
| [change-impact.json](change-impact.json) | Spec-Designer/MO：绑定旧 freeze 与新 plan 摘要的影响审查，供 within-envelope 再冻结 |
| [escalation.md](escalation.md) | Escalation：人工问题与超时 |
| [human-decision.json](human-decision.json) | 真实人类反馈引用，Escalation 规范化、Ledger 接受 |
| [batch-envelope.json](batch-envelope.json) | 父 MO 批量冻结信封；一次人类批准覆盖条目完全匹配的孩子，子 MO 仍附 review_ref |
| [audit-report.md](audit-report.md) | Auditor：全局快照、复测与最终裁决 |
| [workflow-verification.md](workflow-verification.md) | 宿主适配后的行为验收矩阵 |

运行根目录与 ACL 见 [runtime.md](../skills/migration-protocol/references/runtime.md)。JSON 外壳的 schema_version 只标识文档结构，证据规则只有当前一套。宿主仍须执行身份、版本、状态门禁与证据校验，JSON 可解析不代表业务有效。

## 本地控制器附加模板

- [ledger-request.json](ledger-request.json)：CLI 请求，operation 与 payload 见 local-runtime。
- [stage-plan.json](stage-plan.json)：六件套引用、冻结路径与任务、理解证据、批准边界。
- [stage-result.json](stage-result.json)：阶段 tests 结果；implementation 结构见 local-runtime。
- [test-adapter.json](test-adapter.json)：宿主审核过的实际 argv，不是任意用户文本执行入口。

这些模板字段由 contracts.py 做运行期校验；JSON schema 文件位于 migration-ledger/schemas，描述基本交换形状，不能替代业务守卫。

- [global-plan.json](global-plan.json)：全局需求/用例归属验收输入。
- [fix-note.json](fix-note.json)：Fixer 必填修复记忆；通过阶段结果 fix_note_ref 引用。
- [problem-audit-report.json](problem-audit-report.json)：问题审计报告；可执行模块须提供真实 tests result，此模板展示不可执行的 Yellow。

- [audit-closure-plan.json](audit-closure-plan.json)：Auditor 按 finding_id 路由到一个或多个修复模块，精确绑定各方 SPEC 与测试路径。

## Harmony 测试

- [harmony-test-path.json](harmony-test-path.json)：逐 ASSERT 的冻结谓词、验证类型、匹配和时序。
- [harmony-config.json](harmony-config.json)：设备、模型环境引用、压缩/反思/视频配置。
- [harmony-test-adapter.json](harmony-test-adapter.json)：Main argv 与任务超时；不依赖源项目绝对路径。

- [module-slicing.json](module-slicing.json)：global-input.module_slicing.module_import_ref 指向的可选人工模块方案；字段与优先级见 [切片规约](../skills/migration-global/references/slicing.md)。

- [single-module-input.json](single-module-input.json)：单模块入口的两个参数示例（entry_mode/module_name），合并已有项目上下文；根功能 ID、scope、SPEC/Testing list 由 Global 生成，父 MO 继续拆子功能，独立子 MO 执行，父汇总后统一 Auditor。

- [project-context.json](project-context.json)：项目长期 config 内容模板，宿主根据用户输入整理，无 run/module 状态。
- [project-context-request.json](project-context-request.json)：init/update 的 patch、CAS revision、幂等 ID 和用户来源引用。
- [run-request.json](run-request.json)：本次选择、临时覆盖与宿主元数据，prepare 固化后交 Global；用户单模块选择仍只有模式和名称。

- [module-decomposition.json](module-decomposition.json)：父 MO 的子功能拆分方案，绑定全局 planning_context 和认领的 assigned_module，逐子分配 scope/context_refs；GO 接受后登记独立子模块。
- module-input 的 parent_module_id/decomposition_required、scope/context_refs 与子 stage-plan.planning_context/assigned_module 由宿主/角色填充；不增加用户入口参数。project-context.knowledge_paths 用于固化父子共享知识文档。

- [reuse-source.json](reuse-source.json)：project-context/global-input.reuse_sources 的可选外部来源元素；TARGET 自动包含。
- [reuse-catalog.json](reuse-catalog.json)：GO 的功能语义抽取目录，父/子 MO 按需求进一步核验细化。
- [source-impact.json](source-impact.json)：GO 的同 run 来源追加影响报告，完整来源集合、能力目录、全部叶子 replan/unchanged 与父分配评审；与 source-review/reconfigure-sources 配套。
- [reuse-plan.json](reuse-plan.json)：子模块逐需求的能力选择、差异、task/PATH 和接入映射；由 stage-plan.reuse_plan_ref 冻结，Ledger 投影到 change/reuse.md。
- [reuse-fidelity.md](reuse-fidelity.md)：存量源码与选中能力逐行为对齐；reuse-plan.fidelity 绑定源码、报告和复现 PATH/ASSERT，正式结果沿 Main/Ledger 留档。
- [implementation-gap.json](implementation-gap.json)：适配/参考/自主实现均经核验证实不可行时，MO 通过 suspend(reason_code=not-implemented) 接受，生成“未实现”人工提醒；没有可复用库本身不能作为结论。
- implementation.md 说明新增 reuse_trace；控制器检查选中映射的实际版本、task 文件和生产绑定证据。

## 上下文预检工件

[context-readiness.json](context-readiness.json) 是 Coding 的 blocked 起始模板；其他 stage 根据 status.context_requirements 生成完整检查项。经 context-submit 提交，原操作 context_ref 接受；assignment 保留同一报告引用。见 [阶段协议](../skills/migration-protocol/references/context-readiness.md)。

## 功能清单来源与完备性

[feature-inventory.json](feature-inventory.json)：GO 抽取的完整功能清单及源码/用例来源映射；默认用例汇总优先，缺失则源码抽取。global-plan.feature_inventory_ref/feature_owners 接受清单并分配叶子，疑问通过 boundary_review 人工决策。

## 构建与自动化

build 配置可选，空值由 GO 发现；stage-plan/test-paths 示例含 build/unit/static/automation。行为契约（`behavior_contract_required`）要求分配时 behavior_review、plan 的 scenario_trace（scenario_index 由 Ledger 派生）、unit_report 本轮报告与 test IDs；实际模板占位符须替换。仅适用 UI 合并 visual PATH 及 task/scenario/dimension 追溯，不适用 unit 记录依据并移除对应示例。assign 按 test_scope；automation 缺测仍 Yellow、不阻塞独立模块。字段与门禁见 [测试协议](../skills/migration-protocol/references/testing.md)。

- [visual-test-path.json](visual-test-path.json)：逐 runtime 目标视觉路径片段。coverage 必须等于该 UI item，baseline_ref 来自其冻结基线，node_ids 来自该目标真实树节点；声明手势时另绑定 interaction_id。
- [visual-alignment.json](visual-alignment.json)：正式视觉结果片段，record 与本次 captured.visual_alignment 一致，绑定当前代码/HAP/基线；交互列表只含冻结声明，未声明时为空，不照抄占位项或伪造 PASSED。
- [visual-capture-execution.json](visual-capture-execution.json)：受管捕获执行回执；绑定安装、构建、代码、设备、逐屏原图/树与实际命令，原生 worker 自动生成，外部捕获缺绑定时由实际运行器提供 sidecar。
- [interaction-evidence.json](interaction-evidence.json)：automation 声明手势时的条件结果扩展；source-only 无需视觉基线，但 Green 须有冻结动作/起点/预期对应的当前 HAP/代码与实际观测。默认 Harmony 缺此证据时保留断言并记录 Yellow。
- [domain-worker-request.json](domain-worker-request.json)：受限 UI 源分析示例；角色、operation 参数及执行期 assignment/fencing_token 见 [接入协议](../skills/migration-protocol/references/domain-tools.md)。输出由入口固定，不添加任意 output_dir。
- [resource-request.json](resource-request.json)：Implementer/Fixer 资源执行示例；绑定 task_id/resource_item_id、冻结映射与任务写范围。resource-scan 只读候选与变体，转换支持 vector/byte_copy/单项 values。
- [knowledge-request.json](knowledge-request.json)：同一受限 worker 的主题查询示例；query/diagnose/resolve/verify 的 args 与角色范围见 [接入协议](../skills/migration-protocol/references/domain-tools.md)。知识操作不要求 assignment，不自动触发；输出固定本 run staging。
- [visual-test-adapter.json](visual-test-adapter.json)：execute_test 的 adapter JSON；只接已独立产出的原始 alignment，不捕获/修复。声明手势才补 --interaction 参数；当前仅支持 expected=true 的布尔视觉断言。
- global-input.ui_fidelity_required=true 对应标准 prepared run。
- project-context.defaults.quality_gates.dependency_resolution_required 是唯一项目配置入口，bool 默认 false；global-input 顶层同名字段由 prepare 派生，必须继承快照，不能将此示例 false 用作覆盖。
- semantic-model.ui_tree_contract 是完整原生树示例；bindings/events/dynamicRules 为带源码锚点的对象，capabilities 为对象，attachments 为列表。实例化真实源码锚点和采集索引后仍须 strict validate；模板本身不证明源闭包完整。

- [audit-review.json](audit-review.json)：Auditor 待验证清单为空时的独立证据审阅；不能用于跳过 Red/Yellow。

- [migration-report.md](migration-report.md)：GO 收尾展示契约，包含完整 CASE 状态、父 MO 名称、非 Green 原因/证据，以及独立 visual_coverage/fidelity_limitations；source-only/capture-fixture 的未证实范围不能因业务 Green 被省略。本地运行优先使用 Ledger 自动生成的报告。

- [dimension-analysis.json](dimension-analysis.json)：GO/父 MO 四维源闭包、条件适用、目标映射与父子分配；先绑定模块/子模块 scope；下游 stage-plan 先划 tasks.scope，再生成任务四维分析并关联 PATH/ASSERT。

- [audit-code-review.json](audit-code-review.json)：全部 MO 收尾后的独立整体代码审查，含全模块改动/冗余/复用/公共能力/fidelity；CR-* 治理发现先于剩余 Red/Yellow 进入闭环。
- [audit-change-inventory.md](audit-change-inventory.md)：Auditor 必交的本次代码修改清单；模块/功能点、逐文件修改路径及前后快照、代码影响范围、CASE/PATH/query/脚本/断言映射与缺口。由 audit-code-review.json.change_inventory_ref 引用，GO 报告提供同版链接。

- [telemetry-analysis.md](telemetry-analysis.md)：GO/父子 MO/Spec/Auditor 的埋点适用性、事件/参数保真、接入与测试证据；N/A 不创建空任务/用例。
- [telemetry-contract.json](telemetry-contract.json)：适用事件的 stage-plan.telemetry 片段（不是独立 Ledger 请求）；包含事件、任务及业务 PATH/ASSERT。无埋点参照 stage-plan.json 的 N/A 示例。


## 路径实例化约束

[ui-state-test-design.md](ui-state-test-design.md) 并入已有模块 test-design，区分稳定截图目标与瞬态行为；沿 plan.definitions 提交，不另建状态目录。

[visual-execution.json](visual-execution.json) 给出冻结 PATH 配置、run 级设备/模型环境和宿主锁回执样式；[visual-request.json](visual-request.json) 经受限 worker 执行安装/捕获/语义取证，仍由正式测试结果提交验收。

[watchdog-host-state.json](watchdog-host-state.json) 是 Host 的真实状态导出模板，保存到本 run runs/watchdog/host-state.json；不是 Ledger 请求，也不能用模板假冒存活证明。配置与仅监听边界见 [watchdog 协议](../skills/migration-protocol/references/watchdog.md)。

`absolute-run-root` 固定为 `workspace_root/.sdd-runs/run_id`。生成记录的路径模板指向本轮 staging；该路径后的 evidence-path/artifact-name 等占位符只代表文件名/局部相对路径，不得再填绝对根或 ..。Harmony 测试生成配置、导入设计和汇总使用 runs/harmony/sandbox，正式结果使用 runs/harmony/automation/<attempt>；非 Harmony 构建输出使用 runs/build/<attempt>。已提交内容寻址记录以 Ledger 返回的 artifacts 引用为准。输入源码/二方库可外部只读，长期项目模型参考与凭证在 .sdd-migration/harmony，Test-Runner 经 sandbox prepare 复制到本 run runs/harmony/sandbox/environment 后生成 adapter；不得将 .env 填为 evidence_ref。
