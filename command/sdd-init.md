---
description: /sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"] — 初始化项目或指定功能的完整迁移
---

# /sdd-init

## 1. 用法
`/sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"]`

默认 project，按项目范围切片。两个可选参数等价于高层输入中的 entry_mode/module_name，显式命令参数优先；共同覆盖本次运行的选择，不改写原项目输入。也可通过自然语言指定“single-module，模块名为用户登录”。宿主解析名称为字符串，不把它作为 shell 命令。

加载已定位项目的 `<workspace_root>/.sdd-migration/project-context.json`，后续 CLI 显式传入该配置目录。仅首次初始化未指定 --root 时使用当前目录下的 `.sdd-migration`，并固化其父级为 workspace_root；切换 cwd 不新建项目配置。首次用户提供项目资料由宿主保存；明确修改通过 update 增量持久化。旧 JSON 入口可导入长期配置。单模块只需两个选择参数，不新增需要用户填写的模块描述、scope、模块代码路径或 SPEC/用例文件。详细遵守 [项目上下文协议](../skills/migration-protocol/references/project-context.md)。

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 读取/初始化当前项目配置；对用户明确更新执行 project_context.py update，临时条件进入 overrides。宿主生成 run-request 和 run_id；prepare 复制文档并固化项目版本，返回 Global 的分析输入。快照相同请求可幂等恢复，不允许覆盖已有 run 快照。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. Global 只使用 prepare 固化的项目上下文分析；project 执行项目切片，single-module 按模式和名称定位模块，生成 ID/scope/代码路径及 SPEC 草案、Testing list 和审计路径。宿主保存完整 input.json，校验非空规范/用例后，带 project_context_ref/input_ref 提交严格 Ledger init；收到 ACK 后 Global register 根功能（decomposition_required=true），派父 MO decompose；GO decompose-accept 登记子功能后 global-plan，再由独立子 MO 推进。初始化分析工件仅为 staged，不提前派模块 worker 或编码。
5. 输出已提交事件/当前状态/产物路径和下一动作，命令结束。角色内部按授权预算运行；命令不嵌套执行其他 slash command。

## 3. 调用契约
目标角色：[Global-Orchestrator](../Agents/global-orchestrator.md)。宿主用实际可用的任务工具启动，参数只有 package_root、assignment_ref、event_ref；Ledger 按协议串行服务。定义文件不会自动安装或注册不存在的工具。

## 4. 参数验证
run-id/change-name 为 kebab-case，module-id 为 `M[0-9]{3,}`；禁止路径逃逸。single-module 模块名须为非空真实名称；共享项目输入必须可解析。模块 ID、scope、路径、SPEC 和 Testing list 都由 Global 生成，不列为用户入口必填字段。整理后的 Ledger init 输入禁止占位符、未决必填值和零必需用例；尚未 init 的输入澄清由宿主展示，不能声称已有 Ledger 状态。

## 5. 硬约束
命令只解析、门控、提交/查询和派发；无业务代码、无状态双写；叶子不能私传结果；无有效批准不推断已冻结；所有门禁由对应守卫/权限校验再次验证。

## 6. 期望输出
```text
✅ accepted | event=<id> | run=<run-id> | next=<账本动作>
⚠️ blocked | reason=<门禁/依赖/人工> | evidence=<绝对路径或事件>
❌ failed | reason=<实际错误> | recorded=<event-id或transport-unavailable>
```
status 使用 `snapshot sequence=<n>` 及当前三态摘要，不伪造事件接受回执。

## 7. 对应规格
[状态机](../skills/migration-protocol/references/state-machine.md)、[OpenSpec 契约](../skills/migration-protocol/references/openspec.md)。

## 8. 自查
参数与前置有效；工具实际存在；没有越权写入；回执来源可信；恢复指令与 phase 一致。

## 本地实现接入

project_context init/update → prepare → Global 生成完整运行输入 → host Ledger init（绑定 project_context_ref）→ Global register（按拓扑顺序）。具体 payload/命令用法见 [local-runtime.md](../skills/migration-protocol/references/local-runtime.md)。宿主必须把已授权身份绑定到 host-context；不能让请求内自报 role 直接获得权限。控制器不自动启动 Agent，不替宿主写目标代码。

当前本地入口：init 包含 global_spec/new_architecture/requirement_ids → register → global-plan 覆盖验收。验收前允许规格规划，禁止实现派发。

解析可选 module_slicing：验证人工导入引用及摘要；完整功能 use case 可按一级/二级功能目录初分，由 Global 核对 scope/用例。跨模块或不确定业务边界先经人工裁决，再提交带 boundary_review 的 global-plan。详见 [切片规约](../skills/migration-global/references/slicing.md)。

入口范围：project 指完整项目及各功能/子功能；single-module 指一个特定根功能及其子功能。用户仍只给 entry_mode/module_name；GO 生成根功能 SPEC 草稿/Testing list，父 MO 在规划阶段继续拆分子功能，独立子 MO 执行。single_module_id 映射根功能 ID，不限制叶子数量。完整走 GO→父 MO 拆分→子 MO→父汇总→Auditor；详见 [父子 MO 协议](../skills/migration-protocol/references/module-decomposition.md)。

复用输入：宿主保存可选 reuse_sources（用户指定其他项目模块）；TARGET 自动纳入评估。prepare 固化来源范围，GO 提取能力语义目录并结合需求切片，将目录作为 context_refs 交父 MO。新 prepare 运行自动要求复用规划，详见 [二方库协议](../skills/migration-protocol/references/reuse-dependencies.md)。

## 初始化上下文门禁

prepare 与新 Ledger init 默认启用 context_readiness_required。GO 初始化分析后，先提交 global-discovery 报告再 register；父拆分有独立 decomposition 报告，全部子模块登记后再提交 global-planning 报告接受覆盖。用户不需手写预检材料，由对应 Agent/宿主生成。见 [阶段协议](../skills/migration-protocol/references/context-readiness.md)。

## 功能清单来源与完备性

功能发现默认使用提供的测试用例汇总；未提供时由 GO 先理解存量源码、抽取完整功能清单，再生成非空需求/CASE 与 input.json，不要求用户先手写用例。汇总存在也须对照源码查漏；歧义/未知功能先人工介入，明确后再推进受影响规划。

输入可选 build 命令/环境配置；省略时 GO 全目标搜索构建脚本并默认评估 Gradle assemble。新运行启用 split_testing_required，区分构建与自动化环境；后者缺失不阻止已可执行工作。见 [双环节协议](../skills/migration-protocol/references/build-automation.md)。

## 四维规划输入

新运行默认启用 dimension_slicing_required；由 GO 生成每个根模块 dimension_analysis_ref，用户无需手写四维清单。按 [四维协议](../skills/migration-protocol/references/dimension-slicing.md) 先按上下文/功能清单划分模块 scope，再在 register 前完成各模块四维分析；父 MO 先划子模块再分析、子 MO 先划任务再分析，N/A 有证据、未知先澄清。

## 运行位置与再次启动

先定位固定 workspace_root/.sdd-migration；prepare 省略 --run-root，按 run_id 自动派生 .sdd-runs/<run_id>。宿主使用返回的 run_root 调用 Ledger，打开 status.openspec_hub 指向顶层 openspec/runs/<run_id>/workflow.md。同 run 恢复读取现有状态与 assignment，不能重置预算或重新 init；新迁移分配新 run_id 并 prepare。详见 [留存布局](../skills/migration-protocol/references/storage-layout.md)。
