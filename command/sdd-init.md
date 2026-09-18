---
description: /sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"] — 初始化项目或指定功能的完整迁移
---

# /sdd-init

## 1. 用法
`/sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"]`

默认 project，按项目范围切片。两个可选参数等价于高层输入中的 entry_mode/module_name，显式命令参数优先；共同覆盖本次运行的选择，不改写原项目输入。也可通过自然语言指定“single-module，模块名为用户登录”。宿主解析名称为字符串，不把它作为 shell 命令。

默认加载当前工作目录 `.sdd-migration/project-context.json`。首次用户提供项目资料由宿主保存；明确修改通过 update 增量持久化。旧 JSON 入口可导入长期配置。单模块只需两个选择参数，不新增需要用户填写的模块描述、scope、模块代码路径或 SPEC/用例文件。详细遵守 [项目上下文协议](../skills/migration-protocol/references/project-context.md)。

## 2. 编排步骤
1. 读取 [AGENTS.md](../AGENTS.md)、[运行协议](../skills/migration-protocol/references/runtime.md)，解析参数为绝对路径及规范 ID。
2. 读取/初始化当前项目配置；对用户明确更新执行 project_context.py update，临时条件进入 overrides。宿主生成 run-request 和 run_id；prepare 复制文档并固化项目版本，返回 Global 的分析输入。快照相同请求可幂等恢复，不允许覆盖已有 run 快照。
3. 检查现有工件与版本；同请求幂等恢复，不删除、不静默覆盖。普通命令不直接写业务工件或投影。
4. Global 只使用 prepare 固化的项目上下文分析；project 执行项目切片，single-module 按模式和名称定位模块，生成 ID/scope/代码路径及 SPEC 草案、Testing list 和审计路径。宿主保存完整 input.json，校验非空规范/用例后，带 project_context_ref/input_ref 提交严格 Ledger init；收到 ACK 后 Global register/global-plan，再派 MO。初始化分析工件仅为 staged，不提前派模块 worker 或编码。
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

入口模式：默认 `entry_mode=project`，Global 分析项目并切片。`entry_mode=single-module` 时只需 module_name；Global 从项目上下文定位功能并生成模块 ID、scope、代码范围、global_spec/global_test_cases、需求 ID 和审计路径。宿主把 Global 生成的模块 ID 映射到 Ledger init.single_module_id，按生成的写范围 register，完整启动 Global→MO→Auditor。该低层 ID 不是用户模块名，也不是用户必填字段。单模块不能绕过 global-plan、冻结或最终审计。[单模块参数示例](../template/single-module-input.json) 仅含两个入口参数。
