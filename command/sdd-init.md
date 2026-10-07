---
description: /sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"] — 初始化项目或指定功能的完整迁移
---

# /sdd-init

## 1. 用法
`/sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"]`

默认 project，按项目范围切片。两个可选参数等价于高层输入中的 entry_mode/module_name，显式命令参数优先；共同覆盖本次运行的选择，不改写原项目输入。也可通过自然语言指定“single-module，模块名为用户登录”。宿主解析名称为字符串，不把它作为 shell 命令。

加载已定位项目的 `<workspace_root>/.sdd-migration/project-context.json`，后续 CLI 显式传入该配置目录。仅首次初始化未指定 --root 时使用当前目录下的 `.sdd-migration`，并固化其父级为 workspace_root；切换 cwd 不新建项目配置。首次用户提供项目资料由宿主保存；明确修改通过 update 增量持久化。旧 JSON 入口可导入长期配置。单模块只需两个选择参数，不新增需要用户填写的模块描述、scope、模块代码路径或 SPEC/用例文件。详细遵守 [项目上下文协议](../skills/migration-protocol/references/project-context.md#初始化和增量更新)。

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 读取/初始化当前项目配置；对用户明确更新执行 project_context.py update，临时条件进入 overrides。宿主生成 run-request 和 run_id；prepare 复制文档并固化项目版本，返回 Global 的分析输入。快照相同请求可幂等恢复，不允许覆盖已有 run 快照。
3. Global 只使用 prepare 固化的上下文；project 切片，single-module 按名称定位，生成业务规范、需求/CASE 与审计路径。宿主保存并校验完整 input.json，原样提交 init；ACK 后 GO register 根功能，原子根 lean_leaf，其余根 decomposition_required=true。完整 registry 经 global-plan 验收覆盖；MO decompose 可细分或确认原子叶子，GO 接受后按当前分配推进。仅冻结且依赖就绪的叶子可编码，无关根可继续规划。

single-module 模块名须为非空真实名称；共享项目输入必须可解析。GO 定义模块范围；叶子 Spec-Designer 编制实施六件套与上游用例路径，Test-Runner design 按需协助，不列为用户入口必填字段。整理后的 Ledger init 输入禁止占位符、未决必填值和零必需用例；尚未 init 的输入澄清由宿主展示，不能声称已有 Ledger 状态。

## 3. 调用契约
目标角色：[Global-Orchestrator](../Agents/global-orchestrator.md)。

## 4. 对应规格
[项目上下文](../skills/migration-protocol/references/project-context.md#总则)、[模块隔离与全量收尾](../skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 本地实现接入

project_context init/update → prepare → Global 生成完整运行输入 → host Ledger init（绑定 project_context_ref）→ Global register（按拓扑顺序）。

当前本地入口：init 包含 global_spec/new_architecture/requirement_ids → register → global-plan 覆盖验收。验收前允许规格规划，禁止实现派发。

解析可选 module_slicing：验证人工导入引用及摘要；完整功能 use case 可按一级/二级功能目录初分，由 Global 核对 scope/用例。未决业务边界或需求/验收/授权变化先经人工裁决，再提交带 boundary_review 的 global-plan。详见 [切片规约](../skills/migration-global/references/slicing.md#总则)。

入口范围：project 指完整项目及各功能/子功能；single-module 指一个特定根功能及其子功能。single_module_id 映射根功能，不限制叶子数。流程：GO 切片→父 MO 拆分→子 MO 规划/冻结/实现/验证→父汇总→Auditor；详见 [父子 MO 协议](../skills/migration-protocol/references/module-decomposition.md#总则)。

复用输入：宿主保存可选 reuse_sources（用户指定其他项目模块）；TARGET 自动纳入评估。prepare 固化来源范围，GO 提取能力语义目录并结合需求切片，将目录作为 context_refs 交父 MO。新 prepare 运行自动要求复用规划，详见 [二方库协议](../skills/migration-protocol/references/reuse-dependencies.md#总则)。

## 初始化上下文门禁

上下文就绪为必选门禁：global-discovery 报告随 register、decomposition 随 decompose、global-planning 随 global-plan 提交（context_ref）。预检材料由对应 Agent/宿主生成。见 [阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)。

## 功能清单来源与完备性

功能发现默认使用提供的测试用例汇总；未提供时由 GO 先理解存量源码、抽取完整功能清单，再生成非空需求/CASE 与 input.json，不要求用户先手写用例。汇总存在也须对照源码查漏；歧义/未知功能先人工介入，明确后再推进受影响规划。

输入可选 build 命令/环境配置；省略时 GO 全目标搜索构建脚本并默认评估 Gradle assemble。构建与自动化环境分开执行；后者缺失不阻止已可执行工作。见 [双环节协议](../skills/migration-protocol/references/build-automation.md#总则)。

## 四维规划输入

四维分析为必选门禁；由 GO 生成每个根模块 dimension_analysis_ref，用户无需手写四维清单。按 [四维协议](../skills/migration-protocol/references/dimension-slicing.md#总则) 先按上下文/功能清单划分模块 scope，再在 register 前完成各模块四维分析；父 MO 先划子模块再分析、子 MO 先划任务再分析，N/A 有证据、未知先澄清。

## 运行位置与再次启动

先定位固定 workspace_root/.sdd-migration；prepare 省略 --run-root，按 run_id 自动派生 .sdd-runs/<run_id>。宿主使用返回的 run_root 调用 Ledger，打开 status.openspec_hub 指向顶层 openspec/runs/<run_id>/workflow.md。同 run 恢复读取现有状态与 assignment，不能重置预算或重新 init；新迁移分配新 run_id 并 prepare。详见 [留存布局](../skills/migration-protocol/references/storage-layout.md#总则)。
