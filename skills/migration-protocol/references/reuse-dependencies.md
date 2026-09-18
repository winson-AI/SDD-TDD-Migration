# 二方库与已有能力：语义抽取、需求映射和依赖验证

## 1. 作用与边界

复用分析是迁移规划的必经输入。下游 Coding 同时依据 **冻结的模块需求/tasks、目标架构、经过审核的能力映射**；已有库的行为不能倒过来削减需求或替换验收标准。

本流程统一处理两类来源，保留来源区别：

- **目标项目已有能力**：业务模块、公共服务、已接入的二方库及其封装。自动纳入 `TARGET` 检索范围，优先检查已存在的生产实现，避免重复迁移。
- **用户指定的其他项目模块/二方库**：作为显式外部复用来源，读取其指定模块，提取同样的功能语义。存在源码只说明可以分析；能否直接依赖、适配接入或只作为语义参考，必须独立核实。

二方库在这里是组织内部维护的可复用组件；任意外部项目源码不自动成为已发布、可接入的库。`reuse` / `adapt` 表示实际使用能力，`reference` 表示仅借鉴语义，`new` 表示评估后自行实现。目标已有实现优先评估，不强制采用不匹配的能力。禁止按类名、接口名或目录名相似直接宣称功能等价。

读取复用来源不授予修改权限：外部来源默认只读；编码仍限 target 中获分配的 scope/write_paths。确需改提供方、改变公共契约或新增跨模块业务边界时，通过 Ledger 的 CR/依赖/人工决策机制处理，不能把外部仓库静默纳入本次迁移。

## 2. 用户输入、持久化与运行版本

项目配置 `reuse_sources` 为可选数组；留空也必须评估目标项目。用户可只描述其他项目的模块位置和用途，宿主整理成 [reuse-source.json](../../../template/reuse-source.json)：

```json
{
  "reuse_sources": [
    {
      "source_id": "LIB-SEARCH",
      "root": "/work/SharedCommerce",
      "module_paths": ["/work/SharedCommerce/search"],
      "description": "可复用的商品检索、分页和筛选能力"
    }
  ]
}
```

`source_id` 唯一且不能为保留 ID `TARGET`；路径为绝对路径，module_paths 必须包含于 root，省略时使用整个 root。外部选择范围与 target 分离；可以共用一个 monorepo 根目录，只要显式选择的模块不与 target 相交。完整目录结构不代表获准扩大功能范围。

沿用项目上下文 init/update/prepare：数组整体替换，null 删除配置；更新影响新运行，不改旧快照。本轮 source_id/root/module_paths 固定；源代码不全文复制。GO 的语义报告、目录、映射通过 Ledger 版本引用留档；选中的 provider/API/版本解析证据用绝对 path/sha256 固定并在运行时复核。仓库 commit 可辅助定位，不能替代未提交改动、锁文件及实际 API 文件的内容证据。

`status.planning_context.reuse_sources` 同时包含隐式 TARGET 和声明的外部来源，父/子 MO 均可见。未能访问用户指定来源时明确阻塞并请求补全，不能写成“已扫描无匹配”。本地 prepare 检查路径可用性；远程坐标/仓库需宿主先取得可读模块/API 材料，本控制器不会自动下载依赖。

## 3. 按三层编排提取与细化

| 阶段 | 责任 | 必需输出与门禁 |
| --- | --- | --- |
| GO 全局准备与切片 | 将 legacy 需求、目标架构与 TARGET/外部来源一起分析；识别现有公共能力、稳定提供方及消费关系，再划模块 scope | 全局 `reuse-catalog.json` 与抽取报告；经 context_refs 分发。每个声明来源有已评审结论；无候选也有搜索依据 |
| 父 MO 认领与子模块划分 | 读取全局目录，按认领模块的业务需求筛选/补充语义；复用公共能力，统一适配 owner，划分消费者与缺口任务 | 子 scope/context_refs 带适用能力及初步需求映射；避免每个孩子各写一套相同封装；GO 接受相关 DAG/写集合 |
| 子 MO + Spec Designer | 在子功能范围内核验候选，逐条需求形成 `reuse-plan.json`，允许有依据地拒绝候选；形成设计与 tasks | requirement → capability/decision → task → PATH，连同接入路线和真实验证要求进入冻结 plan |
| Implementer / Fixer | 读取冻结映射和语义差异，完成依赖声明、版本解析、DI/入口绑定、适配层或新实现 | 原 Task Trace + reuse_trace + 实际版本/绑定证据；不能临时改提供方、行为契约或以 mock 替代生产实现 |
| Test Runner / 子 MO | 依据需求设计断言，验证复用接线及完整业务路径 | 实际提供方集成测试、适配差异回归、完整模块 DoD；编译/导入成功不等于功能 Green |
| Auditor | 所有 MO 收尾后，聚合依赖和能力映射，检查共享提供方影响，委派 Fixer、Testing 并独立裁决 | 新提供方版本/接线变化使相关消费者旧结果失效；按依赖图复测 owner/source/中间与下游；失败保留根因待人工 |

GO 可以先做粗粒度能力目录；父/子 MO 补充与本模块相关的语义证据，形成新的版本化目录引用。目录不等于冻结批准。不要为无关候选全文扫描所有项目；扫描范围、搜索词/调用链和不适用理由写入报告。所有层级的交接只经 Ledger 引用。

目标提供方同时位于本轮其他 MO 的写范围时，必须有明确 owner 和登记依赖；消费者等待提供方稳定后使用实际版本。控制器按选中 provider_refs 检查其他模块的 write_paths 与依赖关系。现存稳定库不是一个待执行 MO，不应虚构永远等不到完成事件的模块依赖。

## 4. 语义抽取必须回答什么

[reuse-catalog.json](../../../template/reuse-catalog.json) 每个 capability 提供稳定 ID、来源、实际版本/API 证据及以下语义：

1. **业务意图**：完成什么用户行为、可观察结果是什么；沿真实入口→状态/数据→输出定位，不能只有 API 摘要。
2. **输入/输出**：模型、单位、空值、默认值、分页/排序、同步/异步语义。
3. **前置条件与状态**：认证、权限、初始化、缓存/持久化、状态所有权、线程和生命周期。
4. **副作用与失败**：网络/存储副作用、异常、超时、取消、重试及幂等；无副作用也显式写明。
5. **接入约束**：公开入口、版本、平台/框架/API 或 ABI、传递依赖、依赖注入、生产环境绑定，以及与目标架构的兼容性。

报告引用真实源码、API 文档、manifest/锁文件和调用链。抽取是 Agent 的语义分析能力，控制器只检验结构、范围和引用，不能自动证明语义等价。冻结前不执行目标业务测试；可通过阅读源码/API、配置和已有证据判断可行性，Coding 后再正式运行 Main 验证。

## 5. 需求映射与 OpenSpec

使用 [reuse-plan.json](../../../template/reuse-plan.json)，覆盖该子模块的每条全局需求 ID：

| decision | 含义 | Coding 指导 |
| --- | --- | --- |
| reuse | 语义和目标架构兼容，可直接使用 | 指明实际入口、版本、初始化/DI、消费者；保留完整业务验证 |
| adapt | 可复用核心能力，但有明确模型/协议/生命周期差异 | 把匹配点、缺口、转换及额外行为写进 behavior_delta，拆独立适配 tasks 和回归路径 |
| reference | 其他项目能力不能直接接入，但其业务语义有价值 | integration.mode=reference-only；提炼规则，在目标架构内实现，不宣称存在运行时库依赖 |
| new | 经过评估无合适能力，或采用候选会违背需求/架构 | capability_id=null；解释搜索/拒绝理由与剩余实现范围，不能省略评估 |

每条映射含 rationale、behavior_delta、binding_plan、verification、task_ids、path_ids；后三种情况不能通过弱化验收消除差异。实际使用时记录 integration.mode（existing-target/package/source-module/reference-only）、locator、版本、配置、传递依赖和兼容证据。源码引用方式不等于源码复制授权；新增依赖仍遵守项目规则和原有边界决策。

OpenSpec 分工：proposal 说明复用策略和缺口；spec 保持用户可观察行为；design 说明提供方与适配边界；tasks 落接线/适配/剩余实现；checklist 核对映射覆盖、版本、生产绑定及测试；status 引用当前冻结 plan 与依赖问题。`stage-plan.reuse_plan_ref` 将目录和映射纳入 plan 摘要、人工冻结及后续 CR。change/reuse.md 投影当前已接受的 plan；冻结前仅供规划阅读，不表示可以编码。

新 prepare 运行自动要求复用规划；显式外部来源、所有新的子 MO 计划也要求。旧扁平 run 未启用 reuse_required 时兼容原有输入；新的 global-input 默认 reuse_required=true。不存在可复用能力时提交空 capabilities + 有证据的来源评审 + new 映射，不编造库。

## 6. Coding、测试与失败处理

Implementer/Fixer 对每个 reuse/adapt/reference 映射提交 `reuse_trace`：mapping_id、resolved_version、files（属于相应 task_trace）和 binding_evidence_ref。reference 记录借鉴语义落在哪些目标代码，不伪造运行依赖。new 映射由既有 Task Trace 覆盖。

Testing 至少验证正常、边界、异常/取消，以及真实提供方接线、版本/配置和适配差异；预期结果来自业务需求，不能照抄现有库行为充当验收。mock 可辅助诊断，缺少必要真实绑定测试时仍为 Yellow。整体用例和跨模块回归覆盖不能因使用二方库而缩小。

- 本模块接线/适配错误且可修复：保持 Red/Yellow 证据，按既有规则优先一轮 Fixer，再正式 Main 复测。
- 已确认提供方缺陷、依赖不可用、外围条件问题：记录 source/capability/mapping/version、影响消费者及根因，直接留待统一 Auditor；无关模块继续。
- 提供方、锁文件或接入证据发生变化：相关冻结依据失效，保留历史；提交新的版本化目录/映射，按 invalidate/CR/重新冻结恢复。不得原地改旧目录或只替换版本字符串复用旧 Green。
- Auditor 不修改二方库或业务源码；修复委派给合法 owner，外部源码未授权则人工处理或经批准选择新接入方案。复核失败输出根因和证据待人工，不无限重试。

当前脚本在 plan 验证语义结构/映射和来源范围，freeze/dispatch/结果接受/DoD/审计复核已选 provider 与接入证据 hash；未选候选变化不单独使消费者失效。实际包解析、依赖隔离、外部写保护、语义判断和运行测试仍由宿主/Agent/项目执行器完成。不要将结构检查称为完成了功能迁移。
