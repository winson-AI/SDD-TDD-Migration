---
description: /sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"] — 初始化项目或指定功能的完整迁移
---

# /sdd-init

## 1. 用法
`/sdd-init [input.json绝对路径] [--mode single-module --module-name "功能模块名"]`

默认 project，按项目范围切片；两个可选参数等价于高层输入的 entry_mode/module_name，命令参数优先，也可用自然语言指定（"single-module，模块名为用户登录"）。名称按字符串解析，不作 shell 命令。配置目录为已定位项目的 `<workspace_root>/.sdd-migration`，后续 CLI 显式传入；仅首次初始化未指定 --root 时取当前目录并固化其父级为 workspace_root。单模块只需这两个参数，不要求用户填 scope、代码路径或 SPEC/用例文件。详见[项目上下文协议](../skills/migration-protocol/references/project-context.md#初始化和增量更新)。

## 2. 编排步骤
1. 按[命令通用约定](../skills/migration-protocol/references/host-integration.md#命令通用约定)读取入口、解析参数并检查现有工件。
2. 读取/初始化项目配置（明确更新走 project_context.py update，临时条件进 overrides）；宿主生成 run-request 与 run_id，prepare 固化项目版本并返回 Global 的分析输入；返回的 `open_statements`（存量怎样跑、目标在哪验证、资源怎样进目标）先问用户再继续；相同请求幂等恢复，不覆盖已有 run 快照。
3. Global 只用 prepare 固化的上下文：project 切片、single-module 按名称定位根功能，生成业务规范、需求/CASE 与审计路径；宿主校验 input.json（禁止占位符、未决必填值、零必需用例）并原样提交 init；ACK 后 GO 按拓扑序 register 根功能（原子根直接为叶，其余 decomposition_required），global-plan 验收覆盖；MO decompose 细分或确认原子叶，GO 接受后推进。仅冻结且依赖就绪的叶子可编码。

## 3. 契约与规格
目标角色 [Global-Orchestrator](../Agents/global-orchestrator.md)；[切片规约](../skills/migration-global/references/slicing.md#总则)、[父子 MO 协议](../skills/migration-protocol/references/module-decomposition.md#总则)、[模块隔离与全量收尾](../skills/migration-protocol/references/state-machine.md#模块隔离与全量收尾)。

## 4. 接入要点
- 功能清单与用例来源按[切片规约](../skills/migration-global/references/slicing.md#用例来源与切片抓手)；可选 module_slicing 人工导入按引用与摘要验证。
- 上下文就绪、四维分析为必选门禁：global-discovery 随 register、decomposition 随 decompose、global-planning 随 global-plan 提交；GO 生成每个根模块的 dimension_analysis_ref，用户不手写。见[阶段协议](../skills/migration-protocol/references/context-readiness.md#2-精确插入节点)、[四维协议](../skills/migration-protocol/references/dimension-slicing.md#总则)。
- 可选 reuse_sources 由宿主保存，TARGET 自动纳入；GO 提取能力目录交父 MO，见[二方库协议](../skills/migration-protocol/references/reuse-dependencies.md#总则)。可选 build 命令缺省时 GO 搜索构建脚本并评估 Gradle assemble，见[双环节协议](../skills/migration-protocol/references/build-automation.md#总则)。
- 运行位置：prepare 按 run_id 派生 `.sdd-runs/<run_id>`，宿主用返回的 run_root 调用 Ledger，入口为 status.openspec_hub；新迁移分配新 run_id。见[留存布局](../skills/migration-protocol/references/storage-layout.md#总则)。
