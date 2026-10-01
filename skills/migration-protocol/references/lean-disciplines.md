# lean 工程纪律（知识 / 依赖阶梯 / Grill / Git）

从 lean bundle 吸收四项工程纪律，融入 SDD 的规划/冻结/修复门禁。Foundation 知识通过受限 worker 读取，保留原始查询、命中主题和解析证据；不为使用知识加载完整 lean 实现 skill。操作参数与角色范围见 [lean 接入](lean-integration.md)。宿主/角色根据实际范围选择主题和日志，脚本不自动派发或判定根因。

## 1. Foundation / 迁移知识执行与冻结

项目配置唯一入口是 `defaults.quality_gates.dependency_resolution_required`，值必须是 bool，默认 false。prepare 固定到本轮快照及 Global input，Ledger init 按该快照继承；不通过顶层项目字段、字符串 true 或 worker 请求临时开关覆盖。配置更新只影响后续运行。详见 [项目上下文](project-context.md)。

开启后，冻结要求 `plan.dependency_resolution_ref` 指向经 [knowledge_gate.py](../../migration-ledger/scripts/knowledge_gate.py) 校验的解析产物：`schema_version:1`、每条 requirement 有 query 与确切 version/resolved_version；subclosure 只列本切片需要的 API；demo-source 必须标 candidate_only。受限 `foundation-resolve` 的 result.json 可直接作为该引用。纯非 Harmony 范围或本切片没有新增敏感依赖必须给出解析器产生的显式 not-required 结果及 target_matrix；空列表本身不证明不适用。开关关闭只是不增加此冻结门禁，不能免除原有真实依赖/生产接线/构建验证。

冻结始终严格校验，不信任产物的 producer 标签：必须绑定随包 catalog hash、target_root/target_matrix，按 catalog 重算选中条目与版本。原始 Lean 解析结果先通过受限 foundation-resolve 生成本轮受管引用。冻结时核对实际目标平台；后续运行只复核已冻结引用与知识摘要，不因兄弟模块新建平台目录而重判本模块。已声明 dependency_resolution_ref 持续参与 plan 证据检查，修改后不能继续派发。next_step 与实际 freeze 共用纯守卫；缺失/错误证据给出未就绪原因，批准不被提前消费。

- **触发式读取**：knowledge-query 的 topics 返回适用条件；角色依据实际切片选择 topic 或 foundation 查询，只读命中材料，并将结果/引用纳入本阶段上下文。保存引用及读取 ACK 不能单独证明理解正确。
- **外部能力**：Foundation 无匹配时可用 knowledge-query mode=external，读取 Harmony native/ArkTS 候选、record/cookbook 与 hash。上游 probe 明确未接入；以现有 SPEC/任务/PATH 做目标本地验证，不自动运行或安装。每份知识结果含 sdd_adaptation_ref，统一领域概念和三目录资产归属。
- **错误→cookbook**：knowledge-diagnose 读取带 hash 的真实错误片段，按 bundled patterns 返回候选及 cookbook/topic 引用；诊断者仍要核对当前代码/环境并形成有证据的根因。无命中不发明修复建议。
- **版本解析**：GO/MO/Spec-Designer 用 foundation-resolve 将需求解析到 bundled catalog 的确切版本和目标支持；这是目录内解析，不联网解析 Maven/Gradle 依赖，也不自动修改构建文件。
- **接线后核对**：Implementer/Fixer/Test-Runner/Auditor 用 foundation-verify 对照本轮 resolution 与 target_root 内真实 TOML version catalog 的坐标版本，保存核对结果；版本一致不代替编译、链接、HAP 或设备测试。
- **权限与留存**：四个知识操作只读，需宿主认证角色与有效 run 快照，不要求执行 assignment；只写本 run 的 staging/request/result/receipt 工件，不提交 Ledger、不增加生命周期门禁。触发读取与阶段提交仍由原角色执行。

## 2. 依赖决策阶梯（已实现，代码）

[dimensions.py](../../migration-ledger/scripts/dimensions.py) 的 `target_strategy` 在 `reuse/adapt/reference/new` 之外新增：

| strategy | 含义 | 约束 |
|---|---|---|
| `subclosure-port` | 按 pin 版查依赖公共 SCM 源，做最小隔离子闭包 port | 只 port 本切片所需子闭包，不扫无关库面 |
| `capture-fixture` | capture 派生 fixture 置于可替换 Repository/DataSource 边界 | **必填 `replaceable_boundary`**；OpenSpec/结果/裁决须披露；仅证数据→UI 路径，非真实在线 parity |

决策优先级：复用已证兼容的目标实现 → `subclosure-port` → `capture-fixture`；不得为易运行而静默替换内容提供方。

## 3. Grill 纪律（协议）

澄清门只问**不可逆的用户产品决策**（如两个变体取哪个、范围取舍、语义变更）；不问可从源码/目标/SDK/Foundation/capture 查得的事实。融入 [上下文就绪](context-readiness.md) 与 boundary_review：能查证的先查证，人工门只留真正需人裁决项——降低人工门噪音、避免"凭想象"补空。

## 4. Git 纪律（协议）

宿主按项目约定与用户授权归档/合并；SDD 领域工具不自动提交或合并：

- 编辑目标前记录 repo root/branch/HEAD 与确切脏路径；识别 `generatedTrackedPaths`（`.gradle`/`build`/`.idea`/HAP/HSP/`.class`/`.knm`/`.knb`）不混入迁移 diff。
- 需要新 repo、基线提交或分支时由宿主按已有授权执行；不因知识查询或导入 Lean 产物获得新的 Git 权限。
- 归档提交使用明确路径和已接受的当前代码/构建/测试状态，保留 Yellow 缺测说明，不以 Lean 的 BUILD_READY 替代 SDD 验收，不 stage 无关/既有脏文件。
- 不 push/tag/reset/clean/改全局 Git 配置，除非用户明确要求。

见 lean `references/git-discipline.md`（映射 skill 内）。SDD 的 events.jsonl 是控制真相，Git 是回滚/审阅边界，二者分离。
