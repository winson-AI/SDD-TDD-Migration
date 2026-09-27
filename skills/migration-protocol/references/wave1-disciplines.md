# Wave-1 纪律吸收（知识 / 依赖阶梯 / Grill / Git）

从 lean bundle 吸收四项工程纪律，融入 SDD 的规划/冻结/修复门禁。领域工具（Foundation 知识库、query/diagnose、foundation_gate）由映射的 lean skill 提供（见 [lean 集成](lean-integration.md)），SDD 不重造；本页固化其接入契约与 SDD 侧的可校验部分。

## 1. Foundation / 迁移知识 gate（协议）

- 按切片**触发式**加载知识：仅加载当前切片命中的主题（lean `query_knowledge.py` + `knowledge-index.json`），不整包灌入。
- **错误→cookbook**：编译/链接/打包/设备/运行时的稳定错误 → `query_knowledge.py diagnose '<逐字错误>'` → 只加载返回的 cookbook 再修复。
- **版本解析 gate**：冻结前对每个 target 敏感依赖用 `foundation_gate.py resolve` 解析确切版本与 API 子闭包；宿主把解析产物作为 `reuse_plan`/依赖证据的一部分随冻结引用。demo 源码只是候选配置，非编译/设备证明。

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

宿主归档/合并遵循（SDD 不自动合并）：

- 编辑目标前记录 repo root/branch/HEAD 与确切脏路径；识别 `generatedTrackedPaths`（`.gradle`/`build`/`.idea`/HAP/HSP/`.class`/`.knm`/`.knb`）不混入迁移 diff。
- 无 repo 则 `git init`，先审 `.gitignore` 再建 pre-migration baseline commit，在 `a2c/<change-id>` 分支工作，保留既有脏路径。
- Validator `BUILD_READY` 后做**单一**迁移 commit，显式路径，不 stage 无关/既有脏文件。
- 不 push/tag/reset/clean/改全局 Git 配置，除非用户明确要求。

见 lean `references/git-discipline.md`（映射 skill 内）。SDD 的 events.jsonl 是控制真相，Git 是回滚/审阅边界，二者分离。
