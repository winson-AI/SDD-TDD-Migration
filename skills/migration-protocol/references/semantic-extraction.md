# 代码语义抽取（UI / Logic / Resource 机器可读模型）

在子 MO 规划实现阶段，为**四维中 UI/Logic/Resource 的 applicable item** 附一层机器可读、AI 易理解、跨平台解析的语义模型，作为全局视角下的抽象输出。它不新建平行体系：模型挂在四维 item 上，随四维分析一起归档、冻结，并沿既有 `item → TASK → PATH → ASSERT` 追溯，**任务驱动**。校验器 [semantics.py](../../migration-ledger/scripts/semantics.py) 只做结构门禁，语义正确性仍由 Agent 审查（与 [dimensions.py](../../migration-ledger/scripts/dimensions.py) 同原则）。

## 层与 schema

| 维度 | `kind` | schema | 条件表达式 |
| --- | --- | --- | --- |
| UI | `ui-component-spec` | AST 化 JSON 组件树（AMIS/Formily 风格），节点 `{type, props?, children?, bindings?}` | — |
| Logic | `logic-statechart` | XState 式 Statechart `{id, initial, states, states[].on}` | 迁移 `cond` 用 **JSON-Logic** 对象 |
| Resource | `design-tokens` | W3C Design Tokens（叶子令牌含 `$value`，可选 `$type`） | — |
| Resource | `icu-messages` | ICU 兼容 `key → message` 映射 | — |

Adhesive 维暂不纳入语义模型，沿用现有 item 结构。字段示例见 [semantic-model.json](../../../template/semantic-model.json)。

## item 上的记录（结果 / 来源 / 位置）

```jsonc
"semantic_model": {
  "kind": "ui-component-spec | logic-statechart | design-tokens | icu-messages",
  "model_ref": {"path": "...", "sha256": "..."},   // 抽象结果:机器可读 JSON;随四维分析归档进 artifacts/、hash 冻结
  "source": {                                       // 抽象来源
    "origin": "legacy | target | authored",         //   legacy=从存量抽取;target=基于目标现有;authored=无参考新建
    "locator": "path#symbol",                        //   origin=legacy/target 时必填
    "evidence_refs": [ ... ]
  },
  "implementation_location": {"target_path": "/abs", "symbol": "..."}  // 实现位置:目标落点(绝对路径)
}
```

## 核验（结构门禁，presence-triggered）

item 不带 `semantic_model` 时完全不校验——可在子 MO 逐个 UI/Logic/Resource item 增量补齐,不影响既有 run。带 model 时校验:

- `kind` 必须匹配所在维度;对应 schema 必需键齐全(statechart 要 `states`/`initial`∈states、design-tokens 要至少一个 `$value`、icu 要 `key→message` 字符串、json-logic `cond` 为对象)。
- `source.origin` 合法;`target_strategy == new` **禁止** `origin == legacy`(无参考,基于目标项目创建);legacy/target origin 必须带 `locator`;`evidence_refs` 可归档。
- `implementation_location.target_path` 为绝对路径。

校验点在 [dimensions.load](../../migration-ledger/scripts/dimensions.py) 单一钩子,覆盖 GO allocation / 父 MO partition / 子 MO plan / freeze verify 全路径。

**下游必用(保证理解使用)**:实现接受时 [semantics.implementation](../../migration-ledger/scripts/semantics.py) 校验 `implementation_location` 文件真实存在,且该 item 的 `dimension_evidence` 必须带 `semantic_conformance`——其 `model_ref` 回指冻结模型、`evidence_refs` 提供实现落点证据。Implementer 不能无视冻结模型自行实现:缺 conformance 则实现被拒。

## 冻结与投影（保证下游理解使用）

- **冻结**:模型随四维分析进入 `freeze verify`,`freeze_id = plan_hash` hash 锁定;coding 前的冻结即包含这些设计输出。model_ref 字节经 `preserve_refs` 归档到 `artifacts/<sha256>`,不可变。
- **投影(逐模块)**:OpenSpec change 目录生成 `semantics.md`(逐 item 列 kind/source/implementation_location/model_ref),从 `artifacts/` 不可变副本重建,供下游 Agent 直接读取;`manifest.json` 记入文件清单。
- **全局语义上下文**:[openspec_projection](../../migration-ledger/scripts/openspec_projection.py) 聚合所有模块的语义模型为 `ledger/semantic-index.json`(`models` 逐条含 module_id/kind/source/位置/model_ref;`coverage` 逐模块列 applicable / with_model / **missing**),`status.semantic_index` 给出路径。下游/GO 据此看到整个语义上下文,并从 `coverage.missing` 直接看出哪些 applicable UI/Logic/Resource item 尚未附模型(presence-triggered 的覆盖可见性)。

## 任务驱动与新建

- **任务驱动**:模型属于 item,由 `dimension_trace` 映射的 task 实现;无需新增绑定。
- **无参考/复用/适配**:`target_strategy == new` 时 `origin` 取 `target`/`authored`,基于目标项目创建,不要求存量来源。

细节与四维关系见 [四维完整性协议](dimension-slicing.md);状态机守卫见 [状态机](state-machine.md)。
