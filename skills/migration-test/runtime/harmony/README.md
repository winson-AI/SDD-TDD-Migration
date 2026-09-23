# Harmony：独立 uv 自动化测试环境

该目录现在是独立 uv 项目：Python 3.12、独立 `.venv`、可提交的 `uv.lock`、默认 LLM 参考配置与 run 级共享 sandbox 配置。不需要借用 MobileAgenticOperator 的虚拟环境或源码路径。

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
mkdir -p /workspace/migration/.sdd-migration/harmony
cp -n .env.example /workspace/migration/.sdd-migration/harmony/.env
chmod 600 /workspace/migration/.sdd-migration/harmony/.env
```

编辑上述项目 `.env` 填入模型密钥与 HARMONY_DEVICE。旧包内 .env 不自动读取、不删除；需要复用时，在 sandbox prepare 显式指定 --env-file 作为复制来源。运行时使用本 run 的私密副本。uv sync 属于工具安装；执行业务命令时使用 .venv/bin/python sandbox.py，避免启动 uv 时在项目外产生运行缓存。

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

密钥读取：**进程已有环境变量优先于指定 `.env` 的同名变量**；再按上表选择第一个非空的角色/公共变量。运行时读取本 run 的 `runs/harmony/sandbox/environment/.env`；`.sdd-migration/harmony/.env` 或显式 `--env-file` 仅作为首次复制来源，不会从目标工程 cwd 搜索凭证。配置文件只保存变量引用，不生成含真实密钥的 JSON。

用户自主修改：

```sh
cp -n config.default.json /workspace/migration/.sdd-migration/harmony/config.json
# 编辑项目 config.json；密钥只放同目录 .env
.venv/bin/python sandbox.py doctor --root /workspace/migration/.sdd-runs/run-demo
```

- 显式 `--config` 是首次复制的完整配置来源，不做隐式深合并。已准备的 run 不跟随来源更新；重复准备复用现有副本，传入不同内容会拒绝，应为配置变更准备新 run 并重新预检。
- 任意密钥字段可写 `{"env":"MY_MODEL_KEY"}` 或 `{"env":["ROLE_KEY","COMMON_KEY"]}`。后者按顺序取第一个非空值。
- 设备优先级：`--device` → JSON 的 `device` → `HARMONY_DEVICE`。默认不指定设备，不沿用参考项目的 Android `emulator-5554`。
- 可配置 `general / glm / mcp_agent / hypium_mcp_agent`；不自动降级执行器。配置改变须重新完成正式流程的环境预检。
- UI 执行不要求 XMind 转换密钥；XMind 导入也不要求 Executor/Verify 密钥或设备。
- `recording_ref/knowledge_ref` 沿用 `{path,sha256}`。回放只复用导航，每次断言仍采集本轮证据。

默认来源与范围：参考 `MobileAgenticOperator/AutoTest/config/config.yaml`、`.env.example`、`AutoTest/config.py` 和 `uv.lock`；只提取配置/凭证规则。源项目文档与提示词没有变成本包新的编排指令。Harmony 原内核来源仍是 `UPSTREAM.json` 所记录的 HarmonyAgenticTesting，不替换其执行/验证逻辑。

## 4. 本轮共享配置与离线检查

Test-Runner 在首次使用前执行（不连接模型或设备）：

```sh
.venv/bin/python sandbox.py prepare --root /workspace/migration/.sdd-runs/run-demo
# 可选：--config <用户参考配置.json> --env-file <用户凭证来源>
```

默认来源依次为显式参数、`.sdd-migration/harmony` 的项目参考、包内 `config.default.json/.env.example`。复制到：

```text
.sdd-runs/<run_id>/runs/harmony/sandbox/environment/
├── .prepare.lock
├── config.json
├── .env
├── config.native.yaml  # 初始化时存在原生兼容配置才固化
├── manifest.json       # ready 标记、整套文件摘要和 native 缺省
└── preparation.json    # 未提交时的私密恢复内容；提交成功后删除
```

配置目录私有、文件权限 600；所有模块共享一个 run 配置，prepare 加锁并幂等。各 automation attempt 不再各自生成模型配置。doctor/design/adapter/test 也会确保准备完成，生成的 adapter 只引用本 run 路径。参考源之后更新不会覆盖本轮。未配置凭证时复制空白模板，doctor/test 按既有 Yellow 处理；不阻塞独立模块。`.env` 不进入证据、报告或版本控制，进程注入仍优先，Host 需保持本轮注入一致。

整套配置先保存在私密 preparation.json，再写入成员并提交 manifest.json；未完成提交不返回可用环境。失败重试使用原准备内容，参考源变化不会拼接出不同版本。完成后校验成员摘要及 native 缺省，删除准备文件；准备文件含可恢复的凭证内容，同样不得归档到 Ledger 或上传。完整旧环境按现有文件建立兼容基线；无准备记录的不完整旧环境须 Host 核验或另建 run，不从当前参考静默补齐。详见 [环境留存与恢复](../../../migration-protocol/references/storage-layout.md)。

旧 adapter.local.json 是已淘汰的机器专属入口；Test-Runner 使用 adapter 命令在本轮重新生成，不能复用其中指向包内 .env 的命令。

离线检查：

```sh
.venv/bin/python sandbox.py doctor --root /workspace/migration/.sdd-runs/run-demo
```

检查依赖 import、LLM 配置/所需变量、是否明确设备、HDC 是否在 PATH。返回 `ready-for-live-preflight` 或 `yellow-blocked`（exit 2），只显示模型名和检查项，不显示密钥。

**doctor 不是测试通过证据，也不是 Ledger testing ready 报告。** 它不连接设备或模型；宿主仍需确认实际连通、权限、fixture、安装包版本及 provider binding。缺少设备/HDC 时记录 Yellow，不能拿依赖安装成功代替测试执行成功。

## 5. 独立导入与单路径调试

导入 MD/XMind，输出待审核草案，不直接冻结：

```sh
.venv/bin/python sandbox.py design \
  --input /workspace/migration/.sdd-migration/inputs/cases.md --module M001 --output /workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/md-design

.venv/bin/python sandbox.py design \
  --input /workspace/migration/.sdd-migration/inputs/cases.xmind --module M001 --app-name MyApp \
  --output /workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/xmind-design
```

单路径调试使用符合契约的完整 query（示例见 [harmony-test-path.json](../../../../template/harmony-test-path.json) 及完整输入输出文档）：

```sh
.venv/bin/python sandbox.py test \
  --query-file /workspace/migration/.sdd-runs/run-demo/runs/harmony/automation/debug-input/query.json \
  --result-file /workspace/migration/.sdd-runs/run-demo/runs/harmony/automation/debug-attempt/result.json \
  --device YOUR_HARMONY_SERIAL
```

输出 result、observations、媒体与内核报告；exit 0/1/2 对应 Green/Red/Yellow。每次使用新的结果目录。此入口单独运行没有 host receipt，不能直接作为 MO/Auditor 正式验收或声称通过整个模块。正式迁移执行必须走下一节。

独立 test 自动创建缺失的结果父目录；结果文件或该目录下的 harmony 已存在时拒绝覆盖，需使用新的 attempt。缺设备等环境问题仍按 Yellow 输出报告，不因父目录尚未创建而直接崩溃。

原生 `main.py` 保留为上游兼容入口；它不读取本节默认 JSON，也不具备外层 Ledger 断言绑定。新 sandbox 使用 `sandbox.py` 入口。

## 6. 接入 SDD 正式测试

先生成只含命令、不含密钥的 adapter 文件：

```sh
.venv/bin/python sandbox.py adapter \
  --root /workspace/migration/.sdd-runs/run-demo \
  --output /workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/host/adapter/adapter.json
```

结果形状：

```json
{
  "argv": [
    "/absolute/harmony/.venv/bin/python",
    "/absolute/harmony/sandbox.py",
    "test",
    "--config", "/workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/environment/config.json",
    "--env-file", "/workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/environment/.env",
    "--root", "/workspace/migration/.sdd-runs/run-demo"
  ],
  "timeout": 1860
}
```

工作流模式显式传 --root；adapter/design/doctor/汇总输出限 runs/harmony/sandbox，test 结果限 runs/harmony/automation。输入可以读取历史文件，生成 query 由执行器保存本轮。独立模式也要求相同目录结构，可从输出推导 run_root；拒绝跨 run 与符号链接跳转。缺少父目录会创建，新输出不可覆盖。prepare 后即可生成设计和 adapter，不需要先初始化 Ledger。design 示例：`sandbox.py design --root /workspace/migration/.sdd-runs/run-demo --input /workspace/migration/.sdd-migration/inputs/cases.md --module M001 --output /workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/test-designer/new-draft`。独立模式不要求初始化 Ledger，但不因此获得正式验收资格。

正式执行直接使用已同步好的 `.venv/bin/python`，避免在每次测试期间联网解析依赖。移动目录或启动新 run 后重新生成绑定本轮的 adapter。

将 argv、cwd、环境材料提交 testing 预检；`read_refs` 纳入公开配置、lockfile、入口脚本及安装包/fixture 证据。不要上传 `.env` 或把密钥值写入预检、日志、Ledger；环境材料只记录变量名、凭证来源标识和可用性。

项目上下文的 `test_adapter` 字段映射为 `executable=argv[0]`、`args=argv[1:]`、`timeout_seconds=timeout`，另填写目标项目 cwd、query_transport、result_format、environment_ref。长期配置仅保存可跨 run 复用的基础参数，不保存某轮 `--root`；prepare 后为本轮 adapter 绑定 run_root，将完整 argv 写入本轮 testing 预检并接受后再执行。项目配置与 CLI adapter 的两种格式不要混用。

Coding 接受、build Green、testing ready、assignment 获接受后，由宿主执行：

```sh
.venv/bin/python ../../../migration-ledger/scripts/execute_test.py \
  --root /workspace/migration/.sdd-runs/run-demo --module M001 --assignment REAL_ASSIGNMENT_ID \
  --path-id PATH-M001-001 --adapter /workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/host/adapter/adapter.json \
  --cwd /absolute/target-project --output /workspace/migration/.sdd-runs/run-demo/runs/harmony/automation/new-path-attempt
```

逐路径回执汇总：

```sh
.venv/bin/python ../../scripts/harmony_stage.py \
  --root /workspace/migration/.sdd-runs/run-demo --module M001 --assignment REAL_ASSIGNMENT_ID \
  --receipt /workspace/migration/.sdd-runs/run-demo/runs/harmony/automation/path-1/receipt.json --receipt /workspace/migration/.sdd-runs/run-demo/runs/harmony/automation/path-2/receipt.json \
  --output /workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/test-runner/new-stage-result.json
```

随后仍需 submit/accept。`harmony_stage.py` 要求当前 automation scope 每条 PATH 一个回执；缺失路径不能静默省略。原始失败、复测 retest_of、媒体摘要和代码基线继续核验。

兼容历史报告汇总工具要求显式输入/输出，工作流内同样传 --root：

```sh
.venv/bin/python generate_combined_report.py \
  --root /workspace/migration/.sdd-runs/run-demo \
  --history-dir /workspace/migration/.sdd-runs/run-demo/runs/harmony/automation/new-path-attempt/harmony/reports \
  --output /workspace/migration/.sdd-runs/run-demo/runs/harmony/sandbox/auditor/new-summary
```

输出新目录的 index.html，并保留到原报告的相对链接；不再读取工具安装目录的 reports/0812。此兼容 HTML 仅供阅读，正式状态仍由 receipts、冻结 ASSERT 和 Ledger 验收决定；省略 --root 时由受管输出路径推导 run，仍可读取显式指定的历史目录。

## 7. 缺环境、失败和并行隔离

- 自动化环境不可启动：testing 报告仅 `test-environment=blocked`，其他条件满足后，MO 经 `automation-unavailable` 记录逐 PATH Yellow/未执行，保留 build Green，不消耗 Fixer 轮次。
- 缺环境不取消兄弟 MO，也不把 Yellow 回写无关模块；依赖当前可构建代码的下游可继续。本轮可带缺测清单结束，不能宣称功能/fidelity 验证通过。
- 实际 Red/其他可修复 Yellow：只读根因 → 一轮 Fixer → 新代码重建 → 正式 Testing。明确依赖/外围或修复仍失败时留证待统一 Auditor。
- 所有 MO 收尾后，Auditor 处理遗留并做最终独立验证；纯环境缺测保留未验证清单。环境恢复后重新预检、派发和复测，不能直接改 Green。

## 8. Git 与本地数据

仓库级 `.gitignore` 已忽略所有层级 `.env`、`.env.*`、`.venv/`，只放行 `.env.example`；另忽略本目录的 `config.local.json`、`adapter.local.json`、`runs/`、`reports/`、`memory/`。工作流与独立入口新增资产统一放 `.sdd-runs/<run_id>/runs/harmony/`：automation 是执行，sandbox 是辅助请求；.gitignore 中旧包内路径仅防止历史私有文件误上传，不再是默认输出。避免把账号、截图或业务数据放进工作流仓库。

应提交：pyproject、uv.lock、公开默认配置、无密钥 `.env.example`、入口脚本、README。若要共享团队配置，复制成不含密钥的独立公开配置并显式纳入版本控制。

检查忽略规则（在仓库根目录）：

```sh
git check-ignore skills/migration-test/runtime/harmony/.env
git ls-files '.env' '*/.env' '.env.*' '*/.env.*'
```

第二条允许列出 `.env.example`，不应列出任何真实密钥文件。


## 10. 临时文件与兼容入口

执行开始即绑定本 runner 的 temp/cache/sdk，覆盖外部 SDK 输出目录配置；正常返回/异常会清理 temp 并记录 cleanup.json，进程强杀残留也只在本 run 内。正式执行器超时停止子进程组后补做清理。设备锁用本机端口租约，不写 /tmp 锁文件；绑定不可用时保持 Yellow，不能跳过设备独占。扩展 skill 使用 runner cwd 和绝对源码入口，外部 cwd 请求被拒绝；任意 shell 的绝对输出仍须宿主授权与文件权限限制。

原生 main.py 兼容调用也必须提供位于 runs/harmony/automation 内的 --report-dir；历史 --memory-dir 仅作为只读输入，复制 JSON 录制到该次 memory 再回放；XMind 转换默认在该次 design，可显式指定同 run 的 sandbox。原生 YAML 参考配置从 .sdd-migration/harmony/config.native.yaml 复制到本轮 sandbox/environment/config.native.yaml 后读取，应用知识仍从长期参考目录 knowledge/<app>.json 只读加载。Python 内核函数可直接调用，但新输出必须通过与正式入口相同的留存校验；没有 runner 时必须传入受管绝对路径，SDK/设备执行须进入 runner scope。正式工作流使用 sandbox/adapter 入口以应用状态门禁。

工具安装的 .venv/wheel/默认公开配置保持包内；本次运行的模型公开配置与摘要见 environment.json，密钥不入 artifacts。完整映射及设备端边界见 [留存文件系统](../../../migration-protocol/references/storage-layout.md)。


## 底层 API 的输出约束

XMind pipeline、报告/汇总、录制、日志、图片/视频、结果 JSON 均在写入函数校验路径。没有 `SDD_RUNNER_DIR` 时，相对输出和未指定输出会拒绝；不会写回输入文件旁、当前目录或系统临时目录。独立调用可传入 `.sdd-runs/<run_id>/runs/harmony/sandbox/<request>/...` 或 `automation/<attempt>/...` 的绝对输出；外部文件仍可只读输入。

需要默认目录、SDK 或设备调用时，通过本包 `runner_storage.scope(<受管 runner 绝对路径>)` 执行，获得 temp/cache/sdk/cwd 绑定及结束清理；推荐直接使用 sandbox CLI。跨当前 run、符号链接、路径逃逸在写入前拒绝。验证视频的原始外部输入不会被自动清理，裁剪证据单独留存。shell 工具拒绝未设置 runner 或改写存储环境变量，但任意脚本的系统调用仍由宿主权限管理。
