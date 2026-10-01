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
| migration-ledger/tests | 626 |
| migration-test/tests | 47 |
| runtime/harmony/tests | 128 |
| 合计 | **801** |

全部无失败、无跳过。适配器夹具仍有既有 engine.log ResourceWarning，不影响断言。

## 已覆盖

| 范围 | 实际验证 |
| --- | --- |
| 冻结与理解门禁 | 未冻结编码、代码未接受即测试、批准 hash 不符、源码未决/目标可行性 unknown 均拒绝 |
| 变更 | Fixer 越权改 SPEC 拒绝；边界内任务修订可重新冻结；改变验收不能沿用批准 |
| 结果与复测 | 空/遗漏断言、伪装 Green、篡改原始报告拒绝；非 Green 复测需新 test_run_id/retest_of，代码变化拒收旧结果 |
| 真实闭环 | 子进程 Red → 诊断 → Fixer → 正式复测 → 模块 Green；本地修复一轮未过转 waiting-auditor |
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
