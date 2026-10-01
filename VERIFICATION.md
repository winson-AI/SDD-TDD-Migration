# 验证记录

本文件只记录当前版本的验证方式、结果与边界；版本演进见 [README 版本记录](README.md#版本记录)。

## 运行方式

三套测试相互独立，均在临时目录中构造隔离的 legacy/target/run，不读取包内 `.env`、不连接真机或外部 LLM。使用 Python 3.11+（`foundation-verify` 需要 tomllib，视觉比较需要 Pillow，可直接用 Harmony sandbox 的解释器）；禁用字节码、pytest 插件自动加载与缓存，不安装依赖。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider skills/migration-ledger/tests
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider skills/migration-test/tests
```

```bash
cd skills/migration-test/runtime/harmony && PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests
```

## 当前结果

| 测试集 | 通过 |
| --- | ---: |
| migration-ledger/tests | 659 |
| migration-test/tests | 47 |
| runtime/harmony/tests | 128 |
| 合计 | **834** |

全部无失败、无跳过。适配器夹具仍有既有 engine.log ResourceWarning，不影响断言。

## 已覆盖

| 范围 | 实际验证 |
| --- | --- |
| 冻结与理解门禁 | 未冻结编码、代码未接受即测试、批准 hash 不符、源码未决/目标可行性 unknown 均拒绝 |
| 变更 | Fixer 越权改 SPEC 拒绝；边界内任务修订可重新冻结；改变验收不能沿用批准 |
| 结果与复测 | 空/遗漏断言、伪装 Green、篡改原始报告拒绝；非 Green 复测需新 test_run_id/retest_of，代码变化拒收旧结果 |
| 真实闭环 | 子进程 Red → 诊断 → Fixer → 正式复测 → 模块 Green；本地修复一轮未过转 waiting-auditor；`local_fix_rounds` 额外轮次只给仍是 build 的失败，业务失败照常交 Auditor |
| 作者自检与会话 | 实现/修复结果缺 authoring_diagnostics、诊断无日志或版本敏感 API 无固定源码引用均拒收；本地修复游标指向原 Implementer 会话 |
| 静态规格闭合 | build 全绿后同一派发继续 static，再到 automation；passed 场景须给出另一目标文件中的调用位置（reached_from）；审查需覆盖全部冻结需求、引用目标文件中真实存在的符号、逐项判定假实现清单；反模式 present 为 Red 并进入修复；prepared run 必须冻结 static PATH |
| 阅读卡与协议体积 | 每个角色/阶段/UI/复用组合的卡片引用真实小节、包含四条红线且不超过 60KB；游标步骤携带 must_read 与 card_sha256；协议总量与单文件受棘轮测试约束 |
| 提示采纳与流程成本 | assign 回填的会话/阅读卡与建议比对并汇总为 hint_adoption；workflow_cost 按模块统计事件、派发、回执、验收、人工决定与修复轮次并进入收尾报告 |
| 闭包提前审计 | 独立同伴运行中时，已交 Auditor 模块的闭包可先 problem-audit，且只锁闭包；消费者的其他依赖仍在运行时拒绝；最终全量审计仍等待全部收尾 |
| 轻量叶子与批量信封 | lean_leaf 登记需 scope/context/不可再拆审阅；本地轮由 Fixer 自诊断（`fixer_self_diagnosis` 对全部模块开启），未开启的普通模块拒绝；批量信封绑定文件 hash 与父的孩子，条目完全匹配且 MO 附 review_ref 才冻结 |
| 变体冲突 | runtime-spec-variant-conflict 规范化为确认的 human 根因，游标给出 suspend(kind=human)，拒绝派发 Fixer |
| Git 检查点 | 仅在运行分支提交模块文件、既有脏文件不暂存、重复执行复用 HEAD；伪造 blob 被 Ledger 拒绝；开启后无检查点不能 complete |
| 独立审计 | 实现者/修复者/测试作者不能兼任 Auditor；审计只复核遗留并按依赖补回归 |
| 事件与恢复 | 同请求幂等、同 ID 改内容拒绝、过期 revision 拒绝、并发 CAS 单赢家；投影崩溃可重放、伪改投影无效 |
| 依赖/锁/身份 | 未完成生产者不放行；重叠写路径拒绝并行；revoke 后旧 worker 拒收；会话替换需 checkpoint |
| 并行隔离 | 单模块失败/挂起不回写兄弟；全部 MO 收尾后才启动 Auditor |
| 项目上下文 | prepare 固化配置/文档/知识快照；配置更新只影响新 run；快照篡改拒绝 |
| 复用与 provider | 能力目录必须显式 provider owner；null 为稳定基线、非空为唯一叶子 owner；owner 依赖、写权限、环与冲突拒绝；provider/归属证据漂移拒绝 |
| 来源追加 | source-review → reconfigure-sources 仅重规划受影响闭包，保留无关结果与预算 |
| 四维与语义模型 | UI/Logic/Adhesive/Resource 逐层映射到 TASK/PATH/ASSERT；N/A 需源证据；语义模型 hash 冻结 |
| UI 保真 | 原生 collector/selector → UI 树 → 冻结门禁；每个 runtime 目标独立 visual PATH；source-only 不伪造基线 |
| 资源精确性 | 精确策略枚举、源文件事实/qualifier/.9.png/sp 校验；裸附加 ID 不填闭包；跨配置路由需冻结证据 |
| 视觉执行 | 正式 Green 绑定当前代码、本轮构建 HAP、本轮受管 capture 与 assignment/fence；semantic finding 需逐项裁决 |
| 手势 | 仅 Spec 声明的 interaction 生效；Green 需同 HAP/代码的真实设备观测；缺证据为 Yellow |
| Foundation 知识 | 冻结时按随包 catalog 重算解析；demo-source 仅候选；目标 TOML 版本核对 |
| 构建与自动化 | 构建 → 自动化拆分；自动化不可用走 automation-deferred Yellow，不阻塞独立任务 |
| OpenSpec 投影 | global/module/projection/final 分范围核验；模块隔离、内容失真、失效后重新规划 |
| 报告 | 全部 CASE 状态、非 Green 根因与证据进入 migration-report |

## 包级核查

内部 Markdown 相对链接、JSON 模板可解析、Python AST、Skill frontmatter 与 `git diff --check` 另做结构检查；模板保留待实例化占位符，不把占位符当真实证据。

## 尚需宿主/项目集成验证

- 真实宿主的身份绑定、进程终止、每次写入的权限/fencing、自动任务派发与原生 session 恢复。
- 真实项目全量 diff/删除/rename 与任务归属、复杂断言适配、跨运行 flaky 识别、设备/网络环境证据。
- 真实 Gradle/Hvigor 构建、设备安装与截图、外部 LLM 语义裁决质量。
- OpenSpec CLI 实际调用、主分支合并与归档。

本地运行入口、精确能力集与请求字段见 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。
