# Harmony：独立 uv 自动化测试环境

该目录现在是独立 uv 项目：Python 3.12、独立 `.venv`、可提交的 `uv.lock`、默认 LLM 配置与本地 `.env`。不需要借用 MobileAgenticOperator 的虚拟环境或源码路径。

这里的 sandbox 指 **Python 依赖隔离**。它不是容器或操作系统权限沙箱；HDC/设备、文件访问、技能脚本权限和资源锁仍由宿主管理。只初始化依赖不会操作设备或调用 LLM。

## 1. 测试覆盖与模块边界

### 覆盖层级

```text
项目测试汇总 / 源码提取的功能列表
  → GO：根模块 scope + REQ/CASE 分配
  → 父 MO：分解子模块，子 CASE/REQ 并集覆盖整个父范围
  → 子 MO：冻结 SPEC + tasks + build / automation PATH
  → 一条 CASE 可有多条 PATH（不同参数、边界、异常）
  → 一条 PATH 有非空 ASSERT 集合
  → 单 PATH 一次独立执行；汇总 assignment 内所有路径
  → MO 验收 / 全量收尾后 Auditor 独立审计
```

| 边界 | 当前控制方式 |
| --- | --- |
| 子模块不能扩大父范围 | `decomposition.py` 校验 CASE/REQ 子集、scope/out、写路径包含关系；子模块并集须覆盖父范围 |
| 模块 CASE 不能遗漏或越界 | `contracts.validate_plan` 检查已分配 CASE 全映射；`check_module_plan` 检查 PATH 的 CASE 属于本模块 |
| 构建不充当业务 CASE 覆盖 | `test_validation.plan_check` 要求每个 CASE 都有 `kind=automation` 路径；仅关联 build PATH 不允许冻结 |
| 执行不能只挑成功路径 | 模块 assignment 的 `test_scope=automation`；阶段结果 PATH 集合必须等于该 scope 的全部冻结路径 |
| 参数实例分别记账 | 每个实例独立 PATH ID / Name / 参数 / ASSERT；设计期审核展开，不能只用一个名称表示全部参数 |
| 跨模块行为 | 由 GO 明确 owner/依赖，跨模块集成纳入 GLOBAL PATH；不确定业务边界交人工，不由测试内核自行扩大 scope |
| 复用二方库 | 仍以存量功能和 SPEC 为依据，覆盖真实提供方、接线、语义差异及 fidelity 断言；编译或 mock 不能代替业务验证 |
| 验收权限 | 模块阶段 MO 唯一验收；审计阶段 Auditor 唯一验收；内核不改 SPEC、不调 Fixer、不直接写 Ledger |

示例：`CASE-暂停播放` 拆为 `PATH-正常暂停`、`PATH-快速连续点击`、`PATH-网络异常后暂停`。每条 PATH 分别执行、保存断言和证据；关联同一 CASE 的 build 退出码 0 不计入业务测试通过。

结构门禁能证明 **已登记 CASE/PATH 没被省略**，不能自动证明用户测试汇总涵盖所有业务语义。功能清单完整性、源码查漏、边界路径及 ASSERT 是否充分仍由 GO/MO/测试设计审核；不明确时人工决策。也不以流程覆盖率冒充源码行/分支覆盖率。

完整数据样式及流程图见 [automation-input-output.md](../../../../diagrams/automation-input-output.md)。

## 2. 安装独立环境

前置：宿主已安装 uv；真机执行另需 Harmony HDC、明确设备、可访问的模型服务、测试账号/fixture 和与 code_baseline 对应的 App。当前没有迁入 MobileAgenticOperator 的 Android/iOS 驱动。

```sh
cd /absolute/SDD-TDD-Migration/skills/migration-test/runtime/harmony
uv sync --locked
cp -n .env.example .env
chmod 600 .env
```

编辑 `.env` 填入模型密钥与 `HARMONY_DEVICE`。已有本地 `.env` 保留，不覆盖。可用 `uv --cache-dir /writable/cache sync --locked` 显式选择有权限的缓存目录。

依赖由 `pyproject.toml + uv.lock` 固定；关键 OpenAI SDK/Agents/Hypium 版本对齐参考项目的 lock，Hypium MCP 使用已随包保留的相对路径 wheel。没有沿用参考项目中 `/Users/.../Downloads/...` 的机器专属 SDK 源路径。旧 `requirements.txt` 留作上游来源记录，新安装推荐使用锁定的 uv 项目。

## 3. 默认 LLM 配置与用户覆盖

[config.default.json](config.default.json) 的公开配置来自用户提供的 MobileAgenticOperator：

| 用途 | 默认模型 | Provider / 接口 | 密钥优先级 |
| --- | --- | --- | --- |
| Planner | `qwen3.7-plus` | `openai` / DashScope compatible-mode | `DECISION_MODEL_API_KEY` → `DASHSCOPE_API_KEY` |
| Executor | `qwen3.7-plus` | `general` 执行器 / 同接口 | `EXECUTE_MODEL_API_KEY` → `DASHSCOPE_API_KEY` |
| Verify | `qwen3.7-plus` | DashScope compatible-mode | `VERIFY_MODEL_API_KEY` → `DASHSCOPE_API_KEY` |
| XMind 转换 | `deepseek-v4-flash-0731` | `openai` / 同接口 | `XMIND_CONVERT_MODEL_API_KEY` → `DASHSCOPE_API_KEY` |

默认 endpoint：`https://dashscope.aliyuncs.com/compatible-mode/v1`。保留 Planner temperature/top_p=1.0、frequency_penalty=0；XMind temperature=0.2、top_p=0.9、frequency_penalty=0。视频验证启用并保留原片。模型名称按参考配置复用，其账号可用性需运行前确认，安装/doctor 不会发送模型请求。

密钥读取：**进程已有环境变量优先于指定 `.env` 的同名变量**；再按上表选择第一个非空的角色/公共变量。只读当前 sandbox 的 `.env` 或明确 `--env-file`，不会从目标工程 cwd 搜索凭证。配置文件只保存变量引用，不生成含真实密钥的 JSON。

用户自主修改：

```sh
cp config.default.json config.local.json
# 编辑 config.local.json 的模型、endpoint、执行器、预算及引用；密钥留在 .env
uv run --locked sandbox.py doctor --config config.local.json
```

- 显式 `--config` 使用完整替代配置，不做隐式深合并；可直接从默认文件复制修改。
- 任意密钥字段可写 `{"env":"MY_MODEL_KEY"}` 或 `{"env":["ROLE_KEY","COMMON_KEY"]}`。后者按顺序取第一个非空值。
- 设备优先级：`--device` → JSON 的 `device` → `HARMONY_DEVICE`。默认不指定设备，不沿用参考项目的 Android `emulator-5554`。
- 可配置 `general / glm / mcp_agent / hypium_mcp_agent`；不自动降级执行器。配置改变须重新完成正式流程的环境预检。
- UI 执行不要求 XMind 转换密钥；XMind 导入也不要求 Executor/Verify 密钥或设备。
- `recording_ref/knowledge_ref` 沿用 `{path,sha256}`。回放只复用导航，每次断言仍采集本轮证据。

默认来源与范围：参考 `MobileAgenticOperator/AutoTest/config/config.yaml`、`.env.example`、`AutoTest/config.py` 和 `uv.lock`；只提取配置/凭证规则。源项目文档与提示词没有变成本包新的编排指令。Harmony 原内核来源仍是 `UPSTREAM.json` 所记录的 HarmonyAgenticTesting，不替换其执行/验证逻辑。

## 4. 离线检查

```sh
uv run --locked sandbox.py doctor
```

检查依赖 import、LLM 配置/所需变量、是否明确设备、HDC 是否在 PATH。返回 `ready-for-live-preflight` 或 `yellow-blocked`（exit 2），只显示模型名和检查项，不显示密钥。

**doctor 不是测试通过证据，也不是 Ledger testing ready 报告。** 它不连接设备或模型；宿主仍需确认实际连通、权限、fixture、安装包版本及 provider binding。缺少设备/HDC 时记录 Yellow，不能拿依赖安装成功代替测试执行成功。

## 5. 独立导入与单路径调试

导入 MD/XMind，输出待审核草案，不直接冻结：

```sh
uv run --locked sandbox.py design \
  --input /absolute/cases.md --module M001 --output /absolute/new-design-directory

uv run --locked sandbox.py design \
  --input /absolute/cases.xmind --module M001 --app-name MyApp \
  --output /absolute/new-xmind-design-directory
```

单路径调试使用符合契约的完整 query（示例见 [harmony-test-path.json](../../../../template/harmony-test-path.json) 及完整输入输出文档）：

```sh
uv run --locked sandbox.py test \
  --query-file /absolute/frozen-query.json \
  --result-file /absolute/new-attempt/result.json \
  --device YOUR_HARMONY_SERIAL
```

输出 result、observations、媒体与内核报告；exit 0/1/2 对应 Green/Red/Yellow。每次使用新的结果目录。此入口单独运行没有 host receipt，不能直接作为 MO/Auditor 正式验收或声称通过整个模块。正式迁移执行必须走下一节。

原生 `main.py` 保留为上游兼容入口；它不读取本节默认 JSON，也不具备外层 Ledger 断言绑定。新 sandbox 使用 `sandbox.py` 入口。

## 6. 接入 SDD 正式测试

先生成只含命令、不含密钥的 adapter 文件：

```sh
uv run --locked sandbox.py adapter \
  --config config.default.json --output adapter.local.json
```

结果形状：

```json
{
  "argv": [
    "/absolute/harmony/.venv/bin/python",
    "/absolute/harmony/sandbox.py",
    "test",
    "--config", "/absolute/harmony/config.default.json",
    "--env-file", "/absolute/harmony/.env"
  ],
  "timeout": 1860
}
```

正式执行直接使用已同步好的 `.venv/bin/python`，避免在每次测试期间联网解析依赖。移动目录或重建到别的位置后重新生成 adapter。

将 argv、cwd、环境材料提交 testing 预检；`read_refs` 纳入公开配置、lockfile、入口脚本及安装包/fixture 证据。不要上传 `.env` 或把密钥值写入预检、日志、Ledger；环境材料只记录变量名、凭证来源标识和可用性。

项目上下文的 `test_adapter` 字段映射为 `executable=argv[0]`、`args=argv[1:]`、`timeout_seconds=timeout`，另填写目标项目 cwd、query_transport、result_format、environment_ref。项目配置与 CLI adapter 的两种格式不要混用。

Coding 接受、build Green、testing ready、assignment 获接受后，由宿主执行：

```sh
.venv/bin/python ../../../migration-ledger/scripts/execute_test.py \
  --root /absolute/run-root --module M001 --assignment REAL_ASSIGNMENT_ID \
  --path-id PATH-M001-001 --adapter /absolute/harmony/adapter.local.json \
  --cwd /absolute/target-project --output /absolute/new-path-attempt
```

逐路径回执汇总：

```sh
.venv/bin/python ../../scripts/harmony_stage.py \
  --root /absolute/run-root --module M001 --assignment REAL_ASSIGNMENT_ID \
  --receipt /absolute/path-1/receipt.json --receipt /absolute/path-2/receipt.json \
  --output /absolute/new-stage-result.json
```

随后仍需 submit/accept。`harmony_stage.py` 要求当前 automation scope 每条 PATH 一个回执；缺失路径不能静默省略。原始失败、复测 retest_of、媒体摘要和代码基线继续核验。

## 7. 缺环境、失败和并行隔离

- 自动化环境不可启动：testing 报告仅 `test-environment=blocked`，其他条件满足后，MO 经 `automation-unavailable` 记录逐 PATH Yellow/未执行，保留 build Green，不消耗 Fixer 轮次。
- 缺环境不取消兄弟 MO，也不把 Yellow 回写无关模块；依赖当前可构建代码的下游可继续。本轮可带缺测清单结束，不能宣称功能/fidelity 验证通过。
- 实际 Red/其他可修复 Yellow：只读根因 → 一轮 Fixer → 新代码重建 → 正式 Testing。明确依赖/外围或修复仍失败时留证待统一 Auditor。
- 所有 MO 收尾后，Auditor 处理遗留并做最终独立验证；纯环境缺测保留未验证清单。环境恢复后重新预检、派发和复测，不能直接改 Green。

## 8. Git 与本地数据

仓库级 `.gitignore` 已忽略所有层级 `.env`、`.env.*`、`.venv/`，只放行 `.env.example`；另忽略本目录的 `config.local.json`、`adapter.local.json`、`runs/`、`reports/`、`memory/`。实际执行工件建议放在外部 run_root，避免把账号、截图或业务数据放进工作流仓库。

应提交：pyproject、uv.lock、公开默认配置、无密钥 `.env.example`、入口脚本、README。若要共享团队配置，复制成不含密钥的独立公开配置并显式纳入版本控制。

检查忽略规则（在仓库根目录）：

```sh
git check-ignore skills/migration-test/runtime/harmony/.env
git ls-files '.env' '*/.env' '.env.*' '*/.env.*'
```

第二条允许列出 `.env.example`，不应列出任何真实密钥文件。
