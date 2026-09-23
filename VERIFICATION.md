# 收尾投影异常通知与诊断持久化（2026-09-23）

按用户确认修复两处通知遗漏：status 先尝试输出 workflow-attention.md，再保存包含末端错误的 progress.json；机器诊断首次失败最多补写一次，持续失败明确返回给 Host，不循环等待、不追加业务事件。watchdog 在业务终态仍存在 projection-pending 时显示 completed-with-pending-diagnostics，保留通知并继续观察；ack 只确认交付，正常 Host status 重建后关闭告警。显式暂停/停止仍有效，业务质量、调度和验收门禁保持不变。

新增 **6 项**回归：末端报告失败进入持久化诊断、机器诊断暂时失败的有界补写、两个出口持续失败时返回全部错误、真实两叶子完成运行的报告故障与通知 ACK/恢复闭环、Yellow 终态观察输入及显式停止、常驻 watch 等待诊断恢复。新增用例在修复前复现 5 项失败，修复后全部通过；验证观察前后业务资产字节及 mtime、Ledger 事件、质量及独立模块路由保持不变。

全量 **504 项通过，无失败/跳过**：Ledger 329（99.000 秒）、适配层 47（1.625 秒）、Harmony 128（1.22 秒）。静态检查：146 个 Python AST、43 个 JSON、91 个 vendored 摘要、git diff --check 通过。同步旁路监听、进度恢复及留存说明，不新增目录或配置开关。

使用隔离夹具，临时文件随夹具清理；进程查询与 loopback 租约测试获工具许可，不连接真实设备、外部 LLM 或业务 Gradle。原有 engine.log ResourceWarning 保持原状。没有启动业务监听服务、提交或推送 Git。两个诊断出口均不可写时，旧投影可能仍存在，Host 必须处理命令返回错误，不能仅依赖 watchdog。

---

# 执行器中断收尾与 Harmony 整套环境固化（2026-09-22）

本轮修复两组已确认问题：

- 执行器遇到 KeyboardInterrupt/SystemExit 或启动后运行异常，先限时停止/回收当前 attempt，再留存日志、清理状态和取消回执，最后重新抛出原异常。CLI SIGTERM 映射为 SystemExit(143)，保留退出意图；未确认退出时保留临时目录，已取消回执不能接受为正常完成，Host 使用既有停止核验与 revoke/audit-revoke。没有自动续跑或取消其他任务。
- Harmony 以 preparation.json 保存整套私密恢复内容，完成成员写入后提交 manifest.json。失败重试使用原内容；提交后核验全体摘要和 native 缺省，配置不跟随参考变化。完整旧环境按现有内容建立兼容基线，不完整旧环境要求 Host 核验或新 run；不宣称可以验证旧环境的历史版本一致性。准备内容和凭证只留在本 run 私密 environment，提交后删除准备文件，不进入 Ledger/artifacts。

新增 **10 项**故障回归：中断传播/回执与进程退出、运行 I/O 异常、独立写进程尚存时保留 temp、SystemExit 退出码，以及真实 CLI SIGTERM；环境部分写入后参考源删除的恢复、提交标记失败后幂等恢复、native 缺省冻结及新 run 接入、修改/不完整旧环境拒绝、完整旧环境兼容。原并发 prepare 用例继续通过，确认各调用方只获得完整环境。

共 **498 项验证通过**：Ledger 全套 322（85.575 秒），随后新增 CLI SIGTERM 独立回归 1（0.156 秒）；适配层 47（1.626 秒）；Harmony 128（1.41 秒）。无失败/跳过。静态校验：146 个 Python AST、43 个 JSON、91 个 vendored 摘要及 git diff --check。

使用隔离夹具及测试自身进程；真实 CLI 取消测试实际发送 SIGTERM。进程存活测试获准查询本轮进程，设备租约仅绑定本机 loopback。未连接真实设备、外部 LLM 或业务 Gradle；已有 engine.log ResourceWarning 保持原状。强制 SIGKILL/断电无法保证执行 finally，仍按已有 Host 恢复规则处理。未启动业务 watchdog，未提交或推送 Git。

---

# 测试超时回收与 Watchdog 通知交付（2026-09-22）

修复只读复审中复现的两处问题：

- execute_test 的超时后 communicate 再限时 2 秒，保留部分 stdout/stderr；回执 termination 记录信号结果、直接进程退出、输出回收和 Host 待核验事项。脱离进程组的子进程持有管道时及时返回，不宣称所有子进程已停止；临时目录及嵌套 Harmony temp 留在原 attempt。host_stop_required 的回执不能通过验收关闭 assignment，Host 核验停止/隔离后走原 revoke/audit-revoke。正常回收的超时继续原三态与修复流程。
- Watchdog 原子保留带 active 检查点的 notice，通知与状态去重分离。state/latest 写入失败或 stdout 丢失后按同一 notice_id 重放；Host 展示或可靠接收后调用 ack，确认绑定本 run 通知摘要且幂等。ack 使用独立观察器锁，常驻 watch 持锁时仍可确认；全部记录只进入 runs/watchdog、reports/watchdog，不触碰 Ledger、OpenSpec 或业务调度。

新增 **9 项**回归：真实独立进程组持管道的有界回收/部分日志/保留 temp/验收拒绝及停止后 revoke；普通超时回收/清理/验收；latest 写失败、state 写失败、stdout 断开后的重放；旧 notice 兼容；常驻观察锁与业务锁同时持有时仍能幂等 ack；告警关闭再开启的独立通知；未知 ID/符号链接拒绝。原去重测试增加未确认重放及确认后静默，业务资产内容和 mtime 保持不变。

全量 **488 项通过，无失败/跳过**：Ledger 318（86.374 秒）、适配层 42（1.579 秒）、Harmony 128（1.38 秒）。静态检查：146 个 Python AST、43 个 JSON、git diff --check 通过。

使用隔离夹具，测试创建的独立子进程在 finally 清理。真实存活测试获准查询本轮测试进程，设备租约测试仅绑定本机 loopback；未执行真实设备、外部 LLM 或业务 Gradle。原有 engine.log ResourceWarning 仍存在。未安装后台服务、未启动业务 watchdog、未提交/推送 Git；生产 Host 仍须接入实际状态接口及通知展示/ack。

---

# 旁路 Watchdog 与并行恢复信号（2026-09-22）

按用户确认的唯一原则：Watchdog 只观察、留存诊断和通知，不影响工作流/控制流，不提交恢复请求或操作，不派发/恢复 Agent，不获取 Ledger/项目锁，不改变状态、预算、测试结果。check/watch 使用有时限的只读子进程，直接读取已验证事件、进度投影及 Host 导出；不调用会写投影的 ledger.status。自身锁、状态和通知仅在本 run runs/watchdog、reports/watchdog。

同时修正两处已批准的控制器问题：拒绝计数按作用域/revision/operation/reason 的 fingerprint 独立留存并聚合；活动全局审计快照失效时优先提示 Host 确认停止并 audit-revoke，撤销前不再推荐被审计锁禁止的模块 invalidate。停止证据和原权限门禁保持有效。

宿主状态支持实际本机 ps 查询（核对 PID 与启动标识）及 Host API 真实查询导出；未接入、过期、身份不匹配或无进程查询权限时明确 unknown。API 导出必须由宿主接入其实际接口，不将测试夹具或模板当作生产接入。程序只输出通知 JSON/文件，Host 负责展示；没有安装系统服务、启动常驻监听或发送外部消息。

新增 **14 项**回归：并行计数和旧 revision 历史、审计撤销顺序/停止证据、业务文件内容及 mtime 完全不变、真实本地进程/PID 身份、API 导出/过期/暂停、无 assignment 编排进度、持有 Ledger 锁时仍可观察、观察器自身互斥不阻塞 Ledger、超时/损坏日志不修写且不误报恢复、配置冻结/禁止自动模式、符号链接/非法根拒绝、禁用无资产、持续 ready 仅去重通知、明确 Host 停止后监听退出、worker 已退出仍不关闭 assignment。

全套 **479 项通过，无失败/跳过**：Ledger 309（85.636 秒）、适配器 42（1.718 秒）、Harmony 内核 128（0.99 秒）；最后的观察信号调整另回归上述 14 项通过。静态校验通过：146 个 Python AST、43 个 JSON、91 个 vendored 摘要、git diff --check。

受限环境禁止 ps 时先验证到权限限制，获准后完成本次创建的子进程只读查询测试；运行程序在权限不足时返回 unknown，不升级权限。适配器设备租约夹具获准绑定本机 loopback，无外部设备/LLM/真实业务 Gradle；既有原生夹具仍有 engine.log ResourceWarning。隔离夹具均按 cleanup 清理，未提交或推送 Git。

---

# 控制流异常恢复回归（2026-09-21）

本轮修正四项已确认的问题：

- status 识别有效 Implementer/Fixer 的授权工作副本，范围内改码不错误推荐 revoke；SPEC、外部证据、路径重定向与已撤销 worker 的未接受改动仍校验。新基线必须由 submit/accept 验证。
- Yellow 中真实失败断言不会被 automation-unavailable 覆盖为未执行；Harmony 根因摘要同时保留环境问题与失败 ASSERT。当前基线已有 Green 路径保留，纯缺测仍独立收尾。
- Ledger ACK 返回 committed 与 projection 状态；单模块投影失败不会伪装成事务拒绝。已验证所有权的损坏 manifest 原件留存 reports/projection-recovery 后重建；其他归属及符号链接保持原样并报警。
- Ledger、项目配置、Harmony 准备锁默认最多等待 10 秒，SDD_LOCK_TIMEOUT_SECONDS 可配置正有限值；超时输出结构化诊断，不窃取锁、不取消 worker，不再次等待同锁来记录拒绝。

新增 12 项控制器异常回归和 1 项 Harmony 混合失败根因回归，并增强既有全生命周期模拟：在正式 prepared 三目录运行的 Fixer 提交前插入 status，确保不会误撤销，随后真实夹具修复、构建、测试、审计完成；同 run 恢复与新 run 隔离继续验证。投影测试覆盖已提交 ACK、幂等重试、不影响另一模块、损坏原件留存及无权覆盖拒绝；锁测试使用真实进程争用。

全量 **454 项通过，无失败、无跳过**：Ledger 284（68.355 秒）、适配器/留存 42（1.396 秒）、Harmony 内核 128（0.90 秒）。Python AST 142、JSON 42、vendored 文件摘要 91 及 git diff --check 通过。

使用既有 Harmony Python 3.12，不安装依赖；内核 pytest 只读借用本机已有包并禁用自动插件/缓存。适配器初次运行的两项端口互斥测试受执行沙箱限制，获工具许可后复跑全套 42 项通过，只绑定本机 loopback。测试夹具仍出现已有日志文件句柄 ResourceWarning，不影响断言结果。本轮未执行真实业务 Gradle、移动设备、LLM 或实际宿主 Agent 调度；没有新增后台 watchdog。修复证据来自隔离夹具，结束后清理，不保留系统临时测试日志。

---

# 底层写入器留存门禁回归（2026-09-21）

针对“入口已约束、底层仍使用 cwd/来源旁/系统 temp”的差异，新增 AutoTest/storage.py 共用既有 run 布局检查。XMind 未指定输出时仅使用当前 runner/design，无 runner 则拒绝；报告/汇总、日志、录制、图片/视频、时间映射和 Harmony 结果 JSON 在实际写入处校验。临时媒体显式指定受管 temp。HDC 报告与 Hypium MCP 接入绑定本轮输出，SDK 需已进入 runner scope；shell/扩展 skill 不再缺省使用包目录，不能覆盖存储环境变量。视频验证外部来源保持只读，裁剪证据留本轮目录，清理拒绝外部文件。

新增 7 项直接 API 回归覆盖：XMind 不写回源文件旁；各写入器在创建目录前拒绝外部位置；默认输出落入 runner；跨 run/符号链接及创建后的文件重定向拒绝；无 runner 的截图/临时文件拒绝且不触发设备调用；外部视频及 sidecar 不被删除；shell 缺失上下文/覆盖存储变量被拒绝且正常写入留在本轮。既有原生录制/回放、Ledger-Harmony 集成夹具仅调整为受管路径，不添加校验豁免。

全套 **441 项通过，无失败、无跳过**：Ledger 272（66.137 秒）、适配器/留存 41（1.398 秒）、Harmony 128（0.82 秒）。静态检查：141 个 Python AST、42 个 JSON、91 个上游文件摘要及 git diff --check 通过。使用既有 Python 3.12 和本机只读 pytest；禁用字节码、pytest 自动插件和缓存。设备互斥测试获准绑定本机 loopback；没有连接外部设备/模型，没有执行真实业务构建或 LLM 转换。

验证证明本包路径门禁、失败/缺测路由及受控夹具行为。任意外部脚本/插件仍可自行使用绝对路径或改变 cwd，需 Host 按冻结命令与文件权限约束；不是 OS 沙箱。历史低层 Ledger 回归兼容、工具安装/开发验证及设备端目录仍遵守各自已声明边界。

---

# XMind 技能与 run 级 sandbox 配置验证（2026-09-21）

XMind 内置技能改为标准用例 Markdown 转换规则，移除 Windows 临时路径与 PowerShell 教程，使用 macOS 三目录内的输入/输出示例。保留用例分支、参数、预期和优先级；歧义留待审核。

Test-Runner 使用 sandbox.py prepare 将显式参考、长期项目参考或公开 default 复制到 .sdd-runs/<run_id>/runs/harmony/sandbox/environment。配置/凭证跨模块共享，加锁幂等、目录 700/文件 600；adapter 指向本轮副本，原始配置被删除或修改不改变既有 run。原生 YAML 兼容入口同样读取本轮副本。旧本地 adapter.local.json 已移除；包内 .env 保留为显式复制来源，未读取或自动迁移其中密钥。运行配置不可用时，test 入口产出结构化 Yellow；prepare/adapter 的准备错误由 Test-Runner 按环境预检失败处理，独立任务继续。

本次相关回归 **162 项通过**：适配器/存储 34 项（1.570 秒），Harmony 内核 128 项（0.79 秒），无跳过。新增 3 项覆盖配置隔离、私密权限、参考源变化不覆盖、缺失来源不半写、并发准备；原 adapter 测试新增删除参考源后仍可执行及不泄露凭证断言。设备互斥测试使用获准的本地 loopback 绑定，不连接外部设备或模型。XMind Skill 格式、Python AST/JSON、91 个 vendored 摘要及 git diff --check 校验通过。未重跑未修改的 Ledger 全套，未进行真实 LLM 转换或设备测试。

---

# 运行资产与 Harmony 路径治理验证

本轮将构建输出限定为 runs/build/<attempt>，Harmony 的执行/辅助产物限定为 runs/harmony/automation 与 runs/harmony/sandbox；独立入口也需相同 .sdd-runs/run_id 结构，可从显式输出推导 root。项目模型配置/凭证默认读取 .sdd-migration/harmony；公开默认配置与安装依赖仍属包资产。完整原位置→新位置映射见 [留存文件系统](skills/migration-protocol/references/storage-layout.md)。

runner 绑定 TMPDIR/TMP/TEMP、Python tempfile、SDK 输出/工作目录及工具缓存；正常/异常返回清理 temp，清理失败保留在 run 并写 cleanup.json；执行器超时终止进程组后补做清理，receipt 归档 cleanup_ref。设备互斥改为本机端口租约，强杀自动释放，不产生系统临时锁文件。扩展 skill 使用 runner cwd。独立执行复制 query 原文到本次结果目录，保留完整输入依据。

直接 Gradle/gradlew 的实际 argv 仅追加确定的缓存目录参数，保留 requested_argv；验收端重新计算并拒绝夹带其他参数。init.d 的 sdd-storage.init.gradle 保存为 storage_policy_ref，常规 buildDirectory 指向 runner outputs，外部覆盖被拒绝。正式 Ledger CLI 需要 prepare 布局；history 只读重放旧根，旧 init/status/apply 等不能继续外写；低层 API 为历史夹具兼容保留，不是宿主绕过门禁的入口。

全量 **431 项通过，无失败、无跳过**：Ledger 272（65.819 秒）、适配器/存储 31（1.700 秒）、Harmony 内核 128（0.72 秒）。新增覆盖异常清理、清理失败留存、强杀后受管残留、兄弟 attempt 不受清理影响、SDK 外部路径覆盖、跨进程设备互斥/强杀释放、构建超时清理、Gradle wrapper 存储策略与冻结命令追溯/篡改拒绝；既有首轮完成/同 run 重启/第二 run 隔离模拟继续通过。

日志：/tmp/sdd-governance-ledger-final.log、/tmp/sdd-governance-adapter-final.log、/tmp/sdd-governance-harmony-final.log。静态检查：138 Python AST、43 JSON（含忽略的本地 adapter）、1 TOML、80 Markdown 的 615 个本地链接目标、91 上游文件摘要、11 Skill 校验与 git diff --check 通过；日志 /tmp/sdd-governance-static.log。包自身验证日志属于开发验证例外，不是业务迁移 run 资产。

使用既有 Python 3.12/pytest，不安装依赖、不读取包内 .env。端口租约测试因执行环境禁止 loopback bind，获工具执行许可后在允许本地绑定的环境运行；不连接外部设备/LLM 服务。未执行真实 Gradle：Gradle wrapper 为受控 shell 夹具，证明命令/环境/回执/验收控制，不能替代目标 Gradle/插件的构建兼容性验证。任意外部脚本绝对输出及设备端写入仍需宿主权限和前置审核；目录治理不是 OS 沙箱，也不把设备强杀后的清理称为已完成。历史外部资产不自动搬迁/删除或重写 hash。

---

# P1–P4 / P6 验证记录

## 缺失索引时的快照恢复校验（2026-09-21）

经用户批准修复 prepare 的已有快照恢复分支：在返回 duplicate 和登记位置索引之前，显式核对 project_id、run_id、快照 run_root 与请求及实际目录一致。索引和准备记录均缺失时，错误复制目录被拒绝，不写位置索引；原目录随后可正常恢复。无 storage_layout 的合法旧运行仍可在原位置补登记，快照不迁移、不改写。

新增 2 项回归分别覆盖错误副本拒绝/原目录恢复/幂等重试，以及合法旧布局恢复/默认按索引定位。存储专项 19 项通过；全量 **423 项通过，无失败、无跳过**：Ledger 270 项（63.977 秒）、测试适配器 25 项（1.538 秒）、Harmony 内核 128 项（0.81 秒）。日志：`/tmp/sdd-recovery-ledger.log`、`/tmp/sdd-recovery-test.log`、`/tmp/sdd-recovery-harmony.log`。

结构检查通过：136 个 Python、42 个 JSON、1 个 TOML、80 个 Markdown 中 612 处本地链接目标、91 个上游文件摘要与 git diff --check。日志 `/tmp/sdd-recovery-static.log`。使用既有 Harmony Python 3.12 和只读加载的本机 pytest，禁用字节码、自动插件与缓存；未安装依赖或运行真实设备/LLM/业务 Gradle。测试中的旧布局由隔离夹具构造，不提供手工重写真实快照的操作入口。

## 第二轮路径审计修复与全量回归（2026-09-21）

经用户批准落实只读复审的 5 项问题：统一 Ledger/context/OpenSpec 受管写入的路径检查与随机临时文件；自动构建发现排除迁移资产目录及指向其中脚本的链接；Ledger 查询/变更/拒绝诊断前置运行根与 run_id 绑定检查；更新自动化说明中的旧 executions 路径和缺失的 --root；独立 Harmony test 自动创建缺失结果父目录并拒绝覆盖已有结果/attempt。

全量 **421 项通过，无失败、无跳过**：

| 测试集 | 结果 | 耗时 |
| --- | --- | --- |
| migration-ledger/tests | 268 通过 | 66.862 秒 |
| migration-test/tests | 25 通过 | 1.616 秒 |
| runtime/harmony/tests | 128 通过 | 0.87 秒 |

新增 6 项回归覆盖：Ledger 固定临时名/目标链接防护；journal/artifacts 路径防护；context/files 链接视图和临时文件保护；复制 run 被拒绝后原件/副本的事件、投影及诊断文件均不变；构建发现排除历史目录和链接且保留真实模块构建/显式命令；独立 sandbox 在新嵌套目录输出环境 Yellow、重复运行和已有结果不被覆盖。现有全生命周期及同 run/新 run 恢复测试继续通过。

回归过程中修正了运行根规范化的兼容问题：macOS /var 与 /private/var 的系统目录别名先在运行入口规范化，随后仍严格检查运行根内部的 journal、工件和投影路径；新增构建测试预期同样使用规范路径。没有通过放宽内部路径边界消除失败。

环境沿用 Harmony Python 3.12、本机只读 pytest；禁用字节码、pytest 自动插件与缓存，未安装新依赖。最终日志：`/tmp/sdd-path-round2-ledger-final2.log`、`/tmp/sdd-path-round2-test-final.log`、`/tmp/sdd-path-round2-harmony-final.log`。结构检查：136 个 Python、42 个 JSON、1 个 TOML、80 个 Markdown 中 612 处本地链接目标、11 个工作流 Skill、91 个上游文件摘要及 git diff --check 通过，日志 `/tmp/sdd-path-round2-static.log`。

验证限于控制器、适配器、路径故障注入与受控夹具；未运行真实业务 Gradle、移动设备/LLM 或宿主派发。历史运行兼容入口、独立测试模式与工具安装目录保留；路径检查不替代宿主对任意外部命令的操作系统级写权限隔离。

## 路径审计五项修复后的全量回归（2026-09-21）

在只读审计确认并经用户批准后，落实：OpenSpec 投影写入前持久化模块归属、中断缺 manifest 可恢复；写入/清理深层路径拒绝符号链接；prepare 预检与 preparing/failed/prepared 初始化记录；工作流测试辅助输出限定本轮 staging/runs 并创建缺失父目录；统一文档 change 命名、固定配置目录，以及历史报告工具显式输入/输出。独立测试工具模式保留，业务状态仍以 Ledger 为唯一事实。完整目录见 [留存文件系统](skills/migration-protocol/references/storage-layout.md)。

全量 **415 项通过，无失败、无跳过**：

| 测试集 | 结果 | 耗时 |
| --- | --- | --- |
| migration-ledger/tests | 263 通过 | 63.745 秒 |
| migration-test/tests | 24 通过 | 1.384 秒 |
| runtime/harmony/tests | 128 通过 | 0.86 秒 |

本轮新增 10 项回归：输入缺失不创建运行资产；freeze I/O 中断记录原因并恢复，重复 prepare 不改文件；测试辅助路径限当前 staging；事件已提交而 design 投影中断后的无 manifest 恢复；深层/文件/固定临时名符号链接保护；adapter 命令绑定 run_root；MD 设计的嵌套输出与独立兼容；stage 防覆盖/越界；组合 HTML 显式路径、明细链接与独立兼容。

测试环境沿用 Harmony Python 3.12 和只读加载的本机 pytest，禁用字节码/pytest 插件/缓存；未安装新依赖。全量日志：`/tmp/sdd-path-final-ledger.log`、`/tmp/sdd-path-final-adapters.log`、`/tmp/sdd-path-final-harmony.log`。

独立重跑 [simulate_storage.py](skills/migration-ledger/tests/simulate_storage.py)：首轮两叶子完成，包含 Red→Fixer→正式复测、父汇总及独立 Auditor，最终 Green、sequence=62。

| 检查点 | 工作区文件数 | 相比上一阶段 |
| --- | ---: | --- |
| 首次 prepare | 14 | 配置、快照、位置索引、准备记录、OpenSpec owner |
| 首轮规划/冻结 | 159 | 新增 145，含模块 projection-owners |
| 首轮完成 | 280 | 新增 121、修改 21、删除 0 |
| 恢复同 run | 280 | 新增/修改/删除均为 0 |
| 更新输入/配置并启动新 run、完成规划 | 435 | 新增 155、修改 3、删除 0 |

仅主动更新的 architecture.md、user.md 和 project-context.json 被修改；首轮 run/OpenSpec 的内容 hash 保持不变。第二轮仅规划/冻结，未复用旧 Green。证据：`/tmp/sdd-path-lifecycle-final/evidence/report.md`，其中链接首轮/二次启动完整文件清单和逐文件 hash/增删改记录。准备阶段失败证据保留在 preparations，不通过删除历史或绕过审批恢复。

静态回归：136 个 Python AST、42 个 JSON、1 个 TOML、612 个本地 Markdown 目标、11 个工作流 Skill、上游来源清单全部 vendored_sha256 和 git diff --check 通过。日志：`/tmp/sdd-path-final-structure.log`。本地链接检查不证明锚点；故障注入与模拟使用受控 Python 夹具，未执行真实业务 Gradle、设备/LLM、宿主 Agent 派发或 OpenSpec CLI。路径约束不替代宿主对外部命令的文件写权限隔离。

以下保留前次实现与各阶段验证记录。

## 统一资产根、顶层 OpenSpec 与二次启动（2026-09-21）

新项目保存 workspace_root；`.sdd-migration`、`.sdd-runs`、`openspec` 顶层并列。prepare 按 run_id 派生运行根并登记不可变位置索引，同请求重试使用旧快照；不同位置的同 run_id 被拒绝。新运行六件套投影到 `openspec/changes/<run_id>-<module_id>`，`openspec/runs/<run_id>/workflow.md/.json` 作为规格/状态/路由中枢，Ledger 仍是唯一事件事实。测试输出校验本轮 runs 目录；布局传递给下游 planning_context。旧运行按原布局兼容，不自动改写历史 hash 或搬迁文件。完整目录与写入责任见 [留存文件系统](skills/migration-protocol/references/storage-layout.md)。

全量测试 **405 项通过，无失败、无跳过**：

| 测试集 | 结果 | 耗时 |
| --- | --- | --- |
| migration-ledger/tests | 257 通过 | 58.326 秒 |
| migration-test/tests | 20 通过 | 1.314 秒 |
| runtime/harmony/tests | 128 通过 | 1.19 秒 |

新增 7 项存储测试覆盖默认 CLI 三目录布局/中枢恢复、幂等重启与配置更新隔离、run_id 路径冲突/override/符号链接拒绝、已有 OpenSpec 内容不覆盖、测试输出归属、旧低层运行布局兼容，以及真实控制器全生命周期。首轮全量发现 2 处旧测试夹具路径假设（跨 run 注入新快照、读取旧 OpenSpec 地址），已改成匹配的新 run/顶层路径，保留原链接重建与重新规划断言，最终全套通过。

使用同一 Harmony Python 3.12 跑两个 unittest 目录；pytest 8.4.2 只读借用本机已安装 site-packages，禁用自动插件和缓存，运行 Harmony 全 tests。未安装/升级运行依赖。日志：`/tmp/sdd-storage-ledger-final.log`、`/tmp/sdd-storage-adapters.log`、`/tmp/sdd-storage-harmony.log`。

独立模拟脚本 [simulate_storage.py](skills/migration-ledger/tests/simulate_storage.py) 实际执行：配置→prepare→GO/父子 MO 规划/冻结→两个叶子构建与断言→M001 Red/Fixer/复测→父汇总→Auditor 独立审查→Green（sequence=62）。随后恢复同 run；再更新输入与配置，以新 run_id 启动并完成两个叶子规划/冻结，新 run 尚未执行代码或测试。

| 检查点 | 工作区文件数 | 相比上一阶段 |
| --- | ---: | --- |
| 首次 prepare | 13 | 初始配置、冻结上下文、位置索引、OpenSpec owner |
| 首轮规划/冻结 | 156 | 新增 143 |
| 首轮完成 | 277 | 新增 121、修改 21、删除 0 |
| 恢复同 run | 277 | 新增/修改/删除均为 0；事件 sequence 不变 |
| 更新配置并启动新 run、完成规划 | 429 | 新增 152、修改 3、删除 0 |

3 个修改文件是主动更新的 `.sdd-migration/inputs/architecture.md`、`inputs/user.md`、`project-context.json`。首轮 `.sdd-runs/demo`、`openspec/changes/demo-*`、`openspec/runs/demo` 全部保持内容 hash；新 run 新建对应目录与规格，未复用旧 Green。模拟每阶段保存完整路径→内容 hash 清单和逐文件增删改；本机留存入口为 `/tmp/sdd-storage-lifecycle-reviewed/evidence/report.md`，可用脚本在全新目录重跑。

结构检查：135 个 Python 文件 AST、42 个 JSON、11 个工作流 Skill、605 处本地工作流 Markdown 链接目标及 git diff --check 通过。另核对模拟生成的 OpenSpec 中枢本地链接 16 处，无缺失目标。链接目标检查不保证锚点。模拟使用真实 Ledger/prepare/子进程执行器与受控 Python 夹具；语义分析、审批和角色由测试构造，不代表真实宿主派发、业务 Gradle/移动设备/LLM/OpenSpec CLI 验证。任意外部工具写权限仍由宿主限制；构建工具原生工程产物不由本布局强制搬迁。

## 最新全量回归（2026-09-21）

对当前工作区（含埋点适用性增强）重新运行全部三个测试目录，**398 项全部通过，无失败、无跳过**：

| 测试集 | 结果 | 耗时 |
| --- | --- | --- |
| `skills/migration-ledger/tests` | 250 通过 | 50.407 秒 |
| `skills/migration-test/tests` | 20 通过 | 1.311 秒 |
| `skills/migration-test/runtime/harmony/tests` | 128 通过 | 0.85 秒 |

关键控制流覆盖：SPEC 冻结与身份/版本门禁、GO/父子 MO 范围和并行隔离、全部模块收尾后的 Auditor 门禁、Build→Fixer→重建→Automation、自动化环境缺失的 Yellow 分流与下游继续、无全局路径时的遗留问题审计、代码治理及受影响消费者复测、失效重新规划/人工进度信号，以及埋点 N/A 正常完成与证据失效只阻止相关模块。

在包根执行 Ledger 和测试适配器的 `python -m unittest discover -s <测试目录> -v`，使用 Harmony `.venv/bin/python`（Python 3.12）。在 Harmony 目录执行内核全目录 `pytest.main(['-q', '-p', 'no:cacheprovider', 'tests'])`；沿用只读追加本机已有 `/Users/winson/Library/Python/3.9/lib/python/site-packages` 的方式加载 pytest 8.4.2，设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，未安装/升级运行依赖。三组均设置 `PYTHONDONTWRITEBYTECODE=1`。本次日志保存在本机临时文件 `/tmp/sdd-full-ledger.log`、`/tmp/sdd-full-adapters.log`、`/tmp/sdd-full-harmony.log`。

结构检查通过：包内 131 个 Python 文件 AST、42 个 JSON 解析、11 个工作流 Skill 格式校验、工作流 Markdown 中 595 处本地链接目标存在，以及 `git diff --check`。链接检查排除 Harmony 原生文档、代码块和占位符，不证明文档锚点有效；JSON 解析不替代运行时契约测试。检查日志为 `/tmp/sdd-full-structure.log`。

本次未发现需要修改运行时代码的问题，仅补充验证记录。结论限于现有自动化测试覆盖的控制器、适配器和录制/回放契约；未运行真实业务 Gradle 构建、设备/LLM、埋点 SDK/服务端、宿主实际派发或 OpenSpec CLI 集成。业务行为穷尽、语义 fidelity 与影响范围完备性仍需实际项目验证，不能仅凭 398 项通过断言所有真实迁移场景均完备。

## 埋点上报条件控制流（2026-09-21）

GO 功能发现、父子 MO 分配/任务规划、SPEC、四维分析、复用/Coding、Testing 和 Auditor 显式检查埋点适用性；有埋点才做事件/参数/接线与验收层级映射，无埋点有据 N/A 不新增状态、事件、测试、依赖或全局门禁。新增 telemetry-analysis.md、telemetry-contract.json，stage-plan 提供 N/A 示例。可选 telemetry 索引校验任务/业务 PATH/ASSERT 及不可变证据，旧计划缺字段兼容，不视作已证明无埋点。

Ledger 全套 **250 项通过**（47.950 秒，无失败/跳过）；新增 5 项测试覆盖旧计划继续、N/A 模块正常 DoD、不新增测试/修复、适用模块普通任务 N/A、非法事件/构建断言/未知任务拒绝，以及埋点证据失效不阻止独立兄弟派发。Python AST、模板 JSON、变更 Skill、Markdown 链接及 git diff --check 检查通过。

本轮未运行真实埋点 SDK/后端/设备，也未修改自动化内核。事件穷尽、行为映射与断言正确性由 Agent/人工语义审查；本包提供控制和证据契约，实际 emitted/sdk-dispatched/server-received 观测依赖项目 adapter。未知/真实失败仍按原范围与三态处理，不自动承诺 Green。

## Auditor 本次代码修改清单（2026-09-21）

新增 template/audit-change-inventory.md：本轮起点至候选的模块/功能、逐文件修改前后路径、代码影响/公共能力/消费者、CASE/PATH/query/脚本/ASSERT/结果证据与映射缺口。审查 JSON 的 change_inventory_ref 必填，Ledger 校验工件及 hash；GO 报告提供同版链接，旧审查缺少清单或证据变化须补交新版。源码定位与归档证据分开，删除/重命名使用前后快照，避免历史跨文件链接失效。

验证：Ledger 全套 **245 项通过**（46.387 秒），包含新增清单缺失拒绝、历史报告补齐、引用投影和篡改失效测试。相关 Python AST、JSON、migration-audit Skill、117 个本地 Markdown 链接目标与 git diff --check 通过。Markdown 清单的语义内容及追溯完备性由 Auditor 审查，控制器仅验证引用/版本，不自动生成或解析表格。未运行真实业务工程、设备/LLM；本轮未修改自动化执行器，未重复其测试。

## Auditor 整体代码治理前置（2026-09-20）

- 全部 MO 收尾与父汇总有效后，新增独立 audit-code-review：检查全部模块的代码改动、重构、冗余、二方库接入、公共能力和 fidelity，绑定当前 SPEC/code/context。全 Green 不能跳过。
- CR-* 治理发现优先进入既有 audit-collect/plan/route/work/Testing/verdict 闭环，再处理剩余 Red/Yellow；不改写用例三态。实际消费者和依赖下游先等 owner，再完整回归；失败和缺测不能由 owner Green 掩盖。
- 代码/SPEC/context 变化后重新审查；历史快照用摘要绑定，避免旧报告引用 mutable 源码妨碍 Fixer 留证。未解决 finding 不能静默删除，重复发现转人工；批准释放并重新规划实现后，以 recovery_resolutions 绑定决策和新基线独立结案。
- 自动化缺测保留 unverified_findings/历史，不重复 Fixer 或锁住独立下游；代码审查不需要自动化环境。最终审计和缺测收尾均校验当前审查。
- 已同步角色、技能、命令、协议、报告模板和工作流/审计 SVG+PNG。

验证：Ledger 全套 **244 项通过**（46.721 秒），测试适配/sandbox **20 项通过**（0.956 秒），共 **264 项，无失败、无跳过**。新增 9 项治理测试，含真实 Python 补丁/断言执行、Green 治理、旧 Red 保留、消费者失败、自动化缺测、人工恢复及身份/证据/门禁。AST、JSON、4 个变更 Skill、310 个本地 Markdown 链接目标和 git diff --check 通过；两张更新流程图已目视检查。

未运行真实业务工程、设备或 LLM。语义冗余、公共能力必要性、影响范围和 diff 完备性由 Auditor/GO/MO 审查；Ledger 校验覆盖、身份、引用、版本及控制流，不能自动证明语义正确。Harmony 录制/回放内核未修改，本轮没有重复其历史 128 项测试。

## 显式 provider 归属与同 run 来源追加（2026-09-20）

本轮在当前工作区完成以下控制流调整：

- 新 reuse-catalog v2 明确稳定 baseline 或唯一叶子 owner，校验权限、依赖环和活动归属冲突；v1 保持旧校验，选中 provider/ownership/fidelity 的 live hash 不放宽。
- GO source-review 接受全体叶子及父分配的来源影响；Host reconfigure-sources 绑定具体用户批准，创建新版本快照，保留初始快照、链接映射、项目 defaults 和事件历史。
- 受影响依赖闭包回到规划/冻结，无关冻结计划与 Green 保留；阶段上下文需重读。相关 blocker 可按明确批准恢复，其他阻塞、Red/Yellow、已耗预算和修复 memory 保留。
- 来源切换协调 worker，禁止打断活动审计；父 MO 自行重汇总，Auditor 按原遗留范围收尾。provider 本体修改的三层协作沿用既有 CR/invalidate/冻结/依赖恢复，协议中明确旧基线→owner 新版本→消费者复测。

实际执行：Ledger 全套 **235 项通过**（43.701 秒）；测试适配/sandbox **20 项通过**，共 **255 项，无失败、无跳过**。本轮新增 20 项（7 项 ownership + 13 项 source change），包括：

- 宽写范围不推断 v2 baseline 依赖，明确 owner 的权限/依赖、自身 owner、外部 owner/缺字段/循环拒绝、冲突 owner 和 v1 兼容；provider 与归属证据漂移仍拒绝。
- 使用真实 prepare、父子拆分、四维分析与 context receipts，通过 source-review/decision/reconfigure-sources；新旧快照/配置/日志不串写，重试及事件提交后投影失败可恢复。
- 红色模块与绿色兄弟同时存在时，只重新规划受影响模块；真实 Python 子进程 Build/业务断言复测保留 retest_of，父 MO 重新汇总后独立 Auditor 审阅通过，无关 Green 不重跑。
- 真实 Fixer 一轮仍失败后补充来源，预算、失败 memory 和结果不清零；再次失败仍送 Auditor。
- 相关/无关阻塞分离、遗漏父子影响/消费者闭包、错角色/批准/越界配置、来源删除改写、评审过期、活动 worker/审计拒绝及可见恢复信号。

35 个 Ledger Python 文件 AST、38 个 JSON 模板/schema、11 个 Skill 和变更 Markdown 链接目标检查通过；git diff --check 通过。未运行真实业务 Gradle 工程、设备/LLM，未直接使用附件候选补丁或修改用户业务仓。语义归属、影响完备性及四维实现策略仍由运行角色审查；脚本不自动证明语义正确。本轮没有重复执行未修改的 Harmony 录制/回放内核测试，前次 128 项结果见下节。

## 此前全量复查（2026-09-20）

在当前工作区（包含 context/files 链接固化修复与目标已有实现冗余重构规范）重新执行，**363 项测试全部通过，无失败、无跳过**：

| 测试集 | 结果 | 证明范围 |
| --- | --- | --- |
| migration-ledger/tests | 215 通过 | 冻结/身份/版本门禁、父子 MO 分配与并行隔离、构建→Fixer→重建→自动化、Yellow 缺测分流、Auditor 非 Green 范围与空 global_paths、失效重规划/进度提醒、复用 fidelity 与上下文链接快照 |
| migration-test/tests | 20 通过 | 测试输入输出契约、模拟原生执行、sandbox 配置及缺设备 Yellow；从其他工作目录调用适配器 |
| runtime/harmony/tests | 128 通过 | 录制、脱敏、XPath/坐标、回放与重规划；设备/模型使用测试替身 |

在包根执行前两组：

```sh
skills/migration-test/runtime/harmony/.venv/bin/python -m unittest discover -s skills/migration-ledger/tests -v
skills/migration-test/runtime/harmony/.venv/bin/python -m unittest discover -s skills/migration-test/tests -v
```

Harmony `.venv` 未安装 pytest，首次启动源测试集因缺依赖未执行；随后使用同一个 Python 3.12，在 `sys.path` 末尾追加本机已有 pytest 的 site-packages，只读加载后运行 `pytest.main(['-q', '-p', 'no:cacheprovider', 'tests/test_tool_recorder.py', 'tests/test_tool_player.py'])`，128 项通过。未安装或升级运行环境。第三方 hypium 有 1 条无效转义 SyntaxWarning，不影响测试结果。

结构核查通过：32 个 Ledger Python 文件与 5 个测试适配脚本 AST、34 个 JSON 模板与 3 个 Ledger schema 解析、11 个 Skill 校验、变更 Markdown 中 144 个本地链接目标存在、`git diff --check`。链接目标检查不代表所有文档锚点已验证。

**结论边界**：本次验证证明本地控制器与测试适配契约在隔离环境中保持可控，未运行真实业务 Gradle 构建、设备/LLM 测试或宿主自动派发。二方库冗余识别与目标实现清理是新增的 Agent/MO 审查规范；现有测试覆盖复用映射、实际接线证据和 fidelity 门禁，不自动证明业务语义等价或真实目标仓已去重。无须修改运行时代码。

---

本轮修改范围是 SDD-TDD-Migration 工作流包。参考上传的 android-to-kmp 机制，自行实现通用本地控制器；未执行上传包的迁移指令，也没有修改上传目录。

## 实际执行

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s SDD-TDD-Migration/skills/migration-ledger/tests -v
```

76 个 Ledger 测试通过（包含模块收尾门禁、finding 路由、依赖交错、人工恢复，以及既有 Harmony/host 集成回归）。测试全部在 TemporaryDirectory 中使用隔离 legacy/target/run 和可控的 Python 项目适配器；包括真实子进程执行、JSON 结果与日志采集、CLI status 调用。其证明范围是工作流控制及契约，不是某个真实业务模块迁移成功。

## 已覆盖

| 范围 | 实际验证 |
| --- | --- |
| 冻结 | 未冻结编码拒绝、代码未接受时测试拒绝、批准 hash 不符拒绝 |
| 理解门禁 | 源码未决项/目标可行性 unknown 拒绝进入可冻结计划 |
| 变更 | Fixer 越权改 SPEC 拒绝；边界内任务修订可重新冻结；改变验收不可沿用批准 |
| 结果 | 空/遗漏断言与路径、伪装 Green、flaky 标记、被篡改原始报告被拒绝 |
| 真实闭环 | 子进程输出 Red → 诊断 → Fixer → 新 test_run 正式复测 → 模块 Green |
| 部分验证 | source-only/未执行保留 Yellow，不能完成 |
| 复测 | 旧非 Green 必须有新的 test_run_id 和 retest_of；代码变化拒收旧结果 |
| 独立审计 | 实现者不能被分配 Auditor；模块测试和整体路径均独立执行，缺全局审计不全局 Green |
| 事件 | 同请求重复 ACK、同 ID 改内容拒绝、过期 revision 拒绝、两个并发请求只有一个 CAS 成功 |
| 恢复 | 事件落盘后投影崩溃可重放；伪改投影无效；不完整日志停止；证据在事件前保存快照 |
| 依赖 | 未完成生产者不放行；完成后仍需 Global 解除事件；消费者恢复原阶段且不自动 Green |
| 锁/身份 | 重叠路径拒绝并行；未知依赖拒绝；host 停止后 revoke，旧 worker 拒收 |
| 人工/会话 | 无决定不能恢复人工阻塞；原会话替换需要 checkpoint；恢复预算绑定明确决定且累计次数不清零 |

初轮测试暴露并修复了 macOS 路径规范化导致的追溯误拒绝，以及依赖版本变化错误覆盖消费者恢复阶段的问题。

## 包级核查

内部 Markdown 相对链接、JSON 模板/schema 可解析、Python 语法与 Skill frontmatter 另做结构检查；模板保留待实例化占位符，不把占位符当真实证据。

## 尚需宿主/项目集成验证

- 真实宿主的身份绑定、进程终止、每次文件写的权限/fencing、自动任务派发与原生 session 恢复。
- 真实项目全量 diff/删除/rename 与任务归属、复杂断言适配、跨运行 flaky 识别、设备/网络环境证据。
- OpenSpec CLI 实际调用及六件套正式文件物化、主分支合并/归档。
- 协议级独立 Yellow 预算、超时通知、根因 fingerprint 和全局审计预算扩展由宿主策略承担。
- KMP 资源、UI 树、设备截图、Harmony 构建等 P5 专项未接入，未做真实迁移测试。

本地运行入口、精确能力集与请求字段见 [local-runtime.md](skills/migration-protocol/references/local-runtime.md)。

## 2026-09-17 增量验证

再次阅读上传 Lean 的 NEXT/status_payload、blocked_from、require_state 和审计/恢复契约后，增加 8 个回归用例，验证：下一动作及原会话提示、查询不派发、嵌套挂起拒绝、旧任务撤销不能倒退新任务、审计不可覆盖及 ID 不复用/撤销不退还次数、挂起阶段拒收 worker 结果、根因变化重新计算停滞、失效证据不推荐派发、完成模块禁止直接挂起。部分用例同时检查多个相关不变量。

完整 34 个测试通过；仍只证明本地控制器行为，不代表真实 KMP 或宿主集成通过。上传 Skill 文件未修改、未执行。

## 控制流审查后的修复验证

本轮只修改本包，未读取或执行上传迁移包。完整 43 项通过；新增回归验证：

- DoD 暂停后恢复 testing；有效人工决定让游标就绪，旧 Green 不能直接完成。
- 阻塞中 invalidate 后可重规划、冻结、提交；旧批准边界不能绕过未决问题。
- 活动测试阻止诊断；诊断提交不改 phase，MO 接受才允许 Fixer；新测试使旧诊断失效。
- 已知 Yellow 按依赖/环境/人工分流，未知原因诊断；未登记依赖不自动解除。
- within-envelope 游标给出的冻结参数可以实际提交。
- 全局与模块审计失败产生责任项；阻止跳过路由/接受直接再审计；完整走通 MO 重开、修复、正式复测、独立审计，新报告必须关联旧失败。
- PATH ID 跨模块/全局唯一，避免审计问题归属歧义；待修复模块先完成已有重建，依赖未就绪时游标不放行。

兼容性：宿主诊断调用需从 diagnose → assign 更新为 diagnose → diagnosis-accept → assign；审计失败增加 audit-route / repair-accept 操作。没有执行真实宿主派发、OpenSpec CLI 或业务迁移。

## 本轮：全局覆盖、问题审计与 OpenSpec/memory

按用户最新策略补齐：测试设计继续提前；Red/Yellow 优先自动修复一轮；确认依赖/外围问题直接排队交 Auditor；修复生成可复用 memory。当前完整 55 项测试通过，新增 12 项覆盖：

- global-plan 缺需求/用例归属时拒绝、未验收禁止实现、新登记模块使旧覆盖验收失效。
- 一轮仍失败后交 Auditor；可修复代码不能跳过第一轮；已确认外围原因不消耗本地修复轮次。
- 问题审计无需全部模块完成；审计期间阻止业务写入；缺失非 Green 复测链拒收。
- 问题审计 Green 仍经 MO 恢复和 Main 复测/DoD；没有最终全局审计不能全局 Green。
- Auditor 委派修复、MO 验收权限和正式回归绑定；memory 失败不可复用，通过后 verified。
- pre-code 问题报告保持 Yellow，不能执行未生成代码或进入最终审计。
- OpenSpec 六件套自动生成、tasks 勾选、删除视图后重建，定义快照与 freeze 不被视图修改。
- 非法 delta、能力路径逃逸、缺失 tasks checkbox/ID 拒绝。
- 生产者变化保留消费者 waiting-auditor 队列；有可推进模块时避免反复问题审计消耗预算。

本轮包级检查：7 个 Python 文件语法有效、19 个 JSON 可解析、209 个包内 Markdown 链接存在；7 个相关 Skill 的 quick_validate 通过。

兼容性：新 init 必填 global_spec/new_architecture/requirement_ids，实现前 global-plan，Fixer 结果必填 fix_note_ref，定义需合法 OpenSpec delta 与任务 ID。没有自动迁移旧 run。问题/最终审计各有预算，不因撤销返还。

OpenSpec manifest 明确 structural-only；本轮没有执行 OpenSpec CLI、真实宿主派发或真实业务工程迁移。所有测试仍在隔离临时目录执行。

## 本轮：Auditor 跨模块修复后验证

默认收尾改为 audit-collect → audit-plan → audit-route-batch → audit-work → Fixer → 负责模块 Testing/DoD → audit-retest 原发现模块 → audit-verdict。失败停止并输出根因待人工，旧 problem-* 仅保留兼容。

完整 60 项测试通过。新增 5 项使用真实 Python 子进程读取两个模块文件验证：

- M002 暴露依赖问题，实际根因在已 Green 的 M001；未显式入队仍被扫描收集；双方 SPEC/测试上下文绑定后，修复 M001，再测试 M001 和 M002，通过后才使 memory 可复用。
- 修复后 M001 通过但 M002 仍失败：批次 awaiting-human，报告保留根因 owner、结果和上下文；禁止自动重试、普通 resume 或无批准新批次。
- 路由上下文不匹配/未经路由审核不能开始修复。
- 负责模块测试失败即停止，原发现模块不得继续测试。
- 原发现模块代码基线被外部修改时，记录验证阻塞根因并等待人工。

包级校验：9 个 Python 文件语法有效、20 个 JSON 可解析、213 个包内链接存在，相关 3 个 Skill 校验通过。修改范围仅本工作流包；未运行真实业务工程、设备或宿主派发。

失败报告投影：`<run_root>/audit-reports/<batch-id>.json` 和 `.md`。全局修复 memory 在跨模块验证完成前不可复用；失败后人工批准只允许建立新批次，不重置总预算、不把测试改 Green。


## HarmonyAgenticTesting 能力迁移（2026-09-17）

范围：只在本包新增测试内核、输入/输出适配与测试，修改 host 执行器/证据验收接点。源目录只读；源配置凭证、历史报告、用户录制未复制。91 个源文件有逐文件源摘要与迁移后摘要，3 个局部修订明确记录：验证解析/视频证据清理、XMind 全 sheet、special_test 配置传递。

本轮共 **208 项测试通过**：

- **65 项 Ledger 测试**：包含全部原 60 项；新增真实 host 子进程 → Harmony 格式 report → tests stage → submit/accept/DoD、禁止 Yellow 改 Green、媒体修改拒收、超时终止子进程组、缺执行器产生 Yellow。
- **15 项测试模块测试**：完整 query/交错断言、冻结描述替换、五类验证观察、缺媒体/异常/未知 ID、负面文本解析、flaky 留痕、设备锁、MD 草稿保留原文、缺设备结构化 Yellow；3 项使用原生依赖检查实际 decision/报告/录制接线、视频异常清理与 XMind 多 sheet。
- **128 项源项目原测试**：保留的 tool_recorder/tool_player pytest 全通过，覆盖 XPath/坐标/输入/回放/重规划等原有逻辑。

可复现入口（PYTHON 为已安装相应依赖的解释器）：

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s SDD-TDD-Migration/skills/migration-ledger/tests -q
PYTHONDONTWRITEBYTECODE=1 <PYTHON> -m unittest discover -s SDD-TDD-Migration/skills/migration-test/tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=<absolute-runtime-harmony> <PYTHON> -m pytest -q -p no:cacheprovider <absolute-runtime-harmony>/tests
```

本机 Ledger 使用 Python 3.9.6；原生兼容/源回归使用源项目已有只读虚拟环境 Python 3.14.7，测试时载入本机已安装 pytest，不安装/升级环境。未把该机器路径写入运行模板。

结构检查：97 个 Python 文件 AST 有效，24 个 JSON 可解析，238 个非 vendored 文档内链有效（本段和 README 新增链接指向已存在入口），91 个迁移文件与清单摘要一致；migration-test 的 quick_validate 通过。

边界：原生接线测试替换了模型与设备 I/O，host 集成用可控 Python 文件做观测；原测试也大量使用 mock。没有连接真机、调用真实模型、安装 App 或执行真实业务用例。故当前证明源码能力保留及本地契约兼容，不能将 208 项通过解释为真实 UI 测试效果无劣化。最终需用户指定设备、构建和代表用例，进行源版/迁移版同条件对照。

执行使用说明与完整能力映射见 [Harmony 运行协议](skills/migration-test/references/harmony-runtime.md)。


## 所有模块本轮结束后的 Auditor 收尾（2026-09-17）

按最新确认调整：Global 等所有模块本轮 completed 或明确挂起，且无活动 worker/可推进动作后才统一启动 Auditor；实际 subagent 与 Used Skills 由宿主运行。

本轮运行 Ledger 完整测试集，**76 项通过**。新增 11 项：

- 正常 dependency-ready、resume 与未结束的独立模块阻止提前 audit-collect；明确 suspend 后计入本轮收尾。
- 依赖图调度探针验证 A 修复/测试 → B 复测 → C 修复，且原 Green 中间模块需要新证据。
- 同发现模块的两个 finding 可分别路由给不同 owner；单 finding 可有多个 owner；归属引入依赖环时拒绝路由。
- 人工分支不会阻断独立修复；包括通过真实 Ledger 操作与 Python 子进程完成另一模块修复/两侧测试/部分审计报告的回归。
- 失败报告批准后 audit-release 能解锁重新规划；失败结果保持原样。上下文/blocker 未处理时禁止立刻重新收集。
- 释放后批准 recover 可追加预算，保留累计使用量。

早期“无在途 worker 即可审计”行为已经替换；历史章节描述旧验证，不作为当前调度规则。旧 problem-assign 兼容入口也采用本轮收尾门禁。修复批次 schema_version=2，按 finding_id 保存来源、责任和依赖验证；人工决定只释放批次，不隐式批准新 SPEC 或把测试改绿。

结构校验：98 个 Python 文件 AST 有效，24 个 JSON 可解析，243 个非 vendored 文档内链存在；migration-audit/global/module/ledger 四个 Skill 校验通过。

边界：本次未执行真实宿主 Agent 派发、模型调用或真机业务测试；Harmony 内核未修改，未重复运行其独立原生回归。依赖调度的部分组合使用纯状态机测试，独立分支修复和人工恢复另有真实 Ledger 事务/本地子进程回归。

## 功能切片与分阶段验收（2026-09-17）

新增可选 module_slicing 高层输入及人工模块方案模板，明确完整功能 use case 可按一级/二级功能目录初分，再分析 scope、测试列表和模块 SPEC。输入解释与业务边界识别由宿主/Global 执行；没有新增自动目录扫描器。

明确 case_owners 为覆盖范围；模块验收由对应 MO 唯一提交，审计验收由对应 Auditor 唯一提交，完整 Green 且原门禁满足后无需额外会签。新增 global-plan.boundary_review 声明，涉及边界问题时校验真实人工批准，绑定完整 plan 和 registry；消费批准并保留证据引用。

本轮 Ledger 完整测试集 **81 项通过**，新增 5 项覆盖：审核字段缺失/无问题自主接受；缺批准/错误作用域/重复使用批准；方案或注册表变化后的批准失效；未知模块/重复问题；Green 模块的 MO 验收权限、无额外人工批准及审计权限隔离。其余既有审计、恢复与证据回归全部通过。

结构检查：21 个 JSON 模板可解析，3 个变更 Python 文件 AST 有效，69 个相关文档内链可定位，migration-global/module/audit/protocol 四个技能通过 quick_validate。

兼容性：新 global-plan 请求必须包含 boundary_review；旧已接受事件不回写。重新规划时需补充实际边界审核。边界声明的语义真实性、真实宿主模块导入与 Agent 切片效果仍需真实运行验证；本轮未运行模型或真机测试，未修改 Harmony 内核。

## 单模块完整运行入口（2026-09-17）

新增 entry_mode=project/single-module，默认项目级切片；single-module-input 模板直接指定独立模块，复用高层 SPEC/Testing list 字段。宿主将选定模块映射到 Ledger init 的 single_module_id，Global 保留注册、覆盖验收、MO 派发与审计收尾职责。Ledger 拒绝模式错误、缺少选定 ID、追加模块、非空内部依赖及未覆盖全部输入 CASE。

本轮 Ledger 完整测试集 **86 项通过**，新增 5 项：默认项目模式可注册多模块；模式/选定 ID 校验；单模块范围与完整用例约束；单模块通过真实 Ledger 事务和子进程证据完成 MO→独立 Auditor 的 Green 流程；单模块 Red/Yellow 遗留进入统一 audit-collect。

结构检查：22 个 JSON 模板、2 个变更 Python 文件 AST、102 个相关文档内链有效；migration-global quick_validate 通过。旧运行未记录 entry_mode 时仍按 project 解释；无就地模式切换。高层配置解析、真实 Agent 派发与语义独立性审查仍由宿主负责，本次未运行真实宿主 Agent 或真机业务测试。

## 单模块用户输入修正（2026-09-17）

修正上节入口描述：用户仅需指定已划分的独立功能模块、描述与代码上下文，现成 SPEC/Testing list 可选。Global 必须主动识别生成模块级 SPEC 草案、Testing list 和运行级审计路径，再启动 MO 正式规格/测试设计及执行，最后进入 Auditor。默认 project 项目切片保持不变。

single-module-input 增加 description/context_refs；global_spec=null、需求/测试/审计路径空列表表示高层待分析输入，不是可执行的低层请求。宿主先执行 Global 初始化分析并保存 staged 工件，整理为完整非空输入后才提交严格 Ledger init；正式派发与交接仍经 Ledger。输入整理后的 input_ref 可通过现有 init 引用归档保留。本次只修正文档、技能和模板，没有新增模型生成脚本或放宽 Ledger 守卫。

验证：现有 Ledger 全部 **86 项通过**；22 个 JSON 模板可解析，项目/单模块模板默认值已检查，102 个相关文档内链有效，migration-global quick_validate 通过。未实际运行宿主 Agent 的需求生成、真实迁移或设备测试。

## 单模块作为同一入口参数（2026-09-17）

以本节取代此前要求用户提供单模块 description/scope/路径的入口说明。高层仅增加 entry_mode=single-module 与 module_name，沿用项目上下文；single-module-input.json 缩为两个参数示例，global-input 保留 project 默认并提供可选 module_name。Global 定位功能并生成稳定 ID、scope、读写路径、SPEC/Testing list，宿主再映射为原有严格 Ledger init/register，后续 MO 与 Auditor 流程保持完整。

命令定义新增 --mode/--module-name 参数，由宿主解析。没有新增或注册实际 CLI，也未改变 Ledger 低层 single_module_id 契约。无歧义的模块输入不再要求用户额外提供模块资料；未知业务边界仍提具体人工决策。

验证：22 个 JSON 模板可解析，单模块参数恰为两字段、项目默认值校验通过，94 个相关文档内链有效，migration-global quick_validate 通过。运行时代码未修改，本轮未重跑此前 86 项回归或实际启动 Agent。

## 项目上下文持久化闭环（2026-09-17）

新增 project_context.py：宿主 init/update/show/history/prepare。默认工作目录 .sdd-migration 保存当前配置、内容寻址的历史链与用户输入来源副本；patch 递归合并，明确 null 删除，数组替换，锁/CAS/幂等保护更新。允许先保存部分共享输入，prepare 前要求可用根目录与架构。

prepare 固化本次项目版本、临时覆盖、模式/模块名及引用文档。快照与原项目配置/文档独立，同一请求重试仍读取原版本，新请求不能覆盖旧 run。Ledger init 校验 run/root、代码根目录、模式/名称、架构与预算，保存 project_context_ref/project_id/project_revision；后续操作和状态读取验证证据。旧无快照运行继续兼容，新宿主入口必须固化。运行状态和跨角色交接仍只走 Ledger。

本轮完整 Ledger 回归 **99 项通过**（原 86 项 + 新增 13 项）。新测试覆盖初始化、嵌套增量更新/删除/历史、来源副本、幂等/过期更新、并发单赢家、部分配置保存/运行阻塞、身份与字段限制、临时覆盖、单模块选择不污染默认、更新后旧运行稳定/新运行采用新值、脱离原配置目录仍可运行、Ledger 绑定与拒绝错配、手改/损坏拒绝、CLI show/prepare、JSON 来源的独立保存。

结构校验：25 个 JSON 模板、3 个变更 Python 文件 AST、150 个相关文档内链有效；migration-global/ledger/protocol 三个技能校验通过。

本轮使用临时目录和本地进程验证真实配置读写/归档/Ledger 绑定。未为用户实际项目创建配置，未启动真实迁移 Agent 或设备测试。自然语言字段提取、生成业务 SPEC/Testing list 和宿主命令注册仍由宿主执行；配置脚本不提供额外身份认证、整个源码树/设备快照或活动 run 上下文就地替换。需要采用新配置的迁移使用新 run 并重新满足已有门禁。

## 并行 MO 独立执行与全量收尾（2026-09-18）

纠正 GO 主步骤中“队列非空即请求审计”与全量门禁的冲突说明。AGENTS、角色/技能、命令与共享状态机明确：每个 MO 独立推进；全局 Red/Yellow 只做聚合；宿主逐 module_id 收集结果，单个异常不取消其他实例，不批量标失败/挂起。完整 registry 中所有模块基于自身证据完成或明确挂起，且无活动 worker/可推进动作后才统一启动 Auditor。

控制器新增 status.module_rounds，分别列出 registered/settled/unfinished/active/ready 模块与 blockers。有遗留但其他模块未结束时，不返回可启动的审计 operation，而返回 continue_modules / wait_for_modules。audit-collect、兼容 problem-assign、最终 audit-assign 均检查全量收尾门禁；空 registry 和缺少挂起记录不能算收尾。suspend(kind=dependency) 必须有真实不可用的已登记依赖，并保存 dependency_module_ids，拒绝把无关同伴失败当作依赖。

验证：Ledger 全部 **104 项通过**（原 99 项 + 新增 5 项），migration-global/module/protocol 三项 skill 校验通过，git diff --check 通过。新增回归覆盖：Red 经本地一轮修复/失败交接时运行中的独立同伴状态完全不变；同伴仍可正式执行测试并独立 Green；三种审计入口在同伴未结束时拒绝；Yellow 不抑制其他 ready 模块；未开始模块不能跳过；已 Green 同伴保留 Green；无真实依赖的挂起被拒绝；真实依赖仅影响消费者。

测试使用临时目录、真实 Ledger 事务与本地测试适配器进程；未启动真实业务迁移或宿主 Agent。实际 subagent 并行等待、身份和写权限隔离仍由宿主实现，更新后的包要求宿主采用逐模块收尾语义。

## 入口范围、父子 MO 与全局规划上下文（2026-09-18）

本节取代此前 single-module 固定单节点、不再拆分的定义。project 直接指定完整项目；single-module 指定一个根功能及其全部子功能。根功能父 MO 提交拆分，GO 接受后登记独立子 MO；父 MO 负责管理/汇总。根功能初始登记要求 decomposition_required=true；旧扁平节点保留兼容，不静默改写已冻结/执行的历史。

新增 decomposition.py 和 decompose / decompose-accept / module-summary 操作。父节点保存在 module_groups，执行叶子保存在 modules；CASE 全覆盖、写范围包含、全树唯一 ID、内部 DAG 无环与上下文一致性在提交时检查。父只汇总不重复执行，子仍独立 Coding/Testing/Fixer/DoD。全部叶子收尾、各层父 MO 完成当前版本汇总后统一 Auditor；审计补丁导致父汇总失效时须重新汇总。

status.planning_context 为父/子 MO 提供完整 legacy_root/target_root、整体规范、目标架构、本轮项目/规则/知识引用及全局父子分工。拆分和子 plan 绑定当前对象，冻结/派发复核，防止使用过期分工。全局代码只读理解与模块写范围分离；源码语义、重复实现识别和复用方案仍由 Agent 审核，控制器不声称证明 Agent 实际阅读过所有源码。

项目配置新增可选 knowledge_paths；prepare 固化各知识文件内容与摘要。原知识更新不改变旧运行，修改运行快照被拒绝。父子规划引用相同快照，写权限仍由模块 scope、assignment 与锁约束。角色、命令、技能、协议、模板及 SVG/PNG 流程图已同步。

验证：Ledger 全部 **115 项通过**（上一轮 104 项 + 10 项父子编排测试 + 1 项知识快照测试）。覆盖单功能多孩子与内部依赖、project 多根功能、嵌套父 MO 自下而上汇总、兄弟独立进展、父/子共同上下文、越界/环/身份拒绝、过期汇总拒绝、已冻结代码禁止直接拆分、真实审计修复后的重新汇总及最终审计门禁。4 项变更技能校验通过，JSON 模板解析/Python AST/git diff --check 通过；流程图已渲染并目视检查。

未执行真实宿主的业务迁移/设备测试，未自动启动父子 Agent。宿主仍须按新角色协议加载工具与身份、传递全局只读上下文、落实读写隔离及逐模块等待；当前修改未提交或推送。

## 三层作用域与认领契约（当前定义）

本节将上一轮可递归拆 MO 的规划收敛为用户指定的三层：GO 全局划分模块 scope/所需上下文并管理迁移；父 MO 认领模块，在范围内分配子 scope/上下文并看护整个模块；子 MO 认领子功能后拆 tasks，不再创建 MO。旧递归记录保留读取/汇总兼容，新拆分不增加层级。

新增 status.module_inputs 权威分配包（子包保留 parent_context）；父拆分、子 plan 用 assigned_module 确认认领范围，同时保留共同 planning_context 全局可读视野。新根模块/孩子必须提供 scope.in/out/全局 requirement_ids 与 context_refs。检查父子需求/CASE 包含及完整覆盖、父排除项继承、上下文 hash、分配包一致性、子 task 全局需求映射、测试 CASE 范围；global-plan 的需求 owner 也须匹配获分配子范围。正式子 plan、freeze、dispatch 重验。宿主继续负责实例与模块绑定、业务语义审核和实际调度，分配包不是自报身份授权。

验证：Ledger 全部 **120 项通过**。替换嵌套拆分测试为子 MO 只拆 tasks 的测试，新增父分配确认/子边界继承、task/CASE 越界拒绝、上下文被改后的派发拒绝、GO 根登记输入门禁、父子需求覆盖检查。已有独立 MO、父汇总和 Auditor 修复复测回归保持通过。4 项技能校验、JSON 模板解析、Python AST 和 git diff --check 通过；SVG/PNG 已更新并目视检查。

本轮未运行真实宿主迁移或设备测试；修改保留在本地工作区。

## 二方库与功能语义复用（2026-09-18）

新增复用协议和 reuse-source / reuse-catalog / reuse-plan 模板。TARGET 自动纳入能力评估；用户指定的其他项目模块使用 reuse_sources 保存/更新并按 prepare 固化，父子共同上下文可见。GO 建功能语义目录并结合需求切片；父 MO 统一复用/适配分工；子 MO 将直接复用、适配、语义参考或新实现映射至每条需求、tasks 和 PATH，stage-plan.reuse_plan_ref 纳入冻结。角色、技能、入口、OpenSpec/Testing/上下文协议及流程图已同步。

reuse.py 校验来源和证据范围、完整功能语义字段、来源评审、需求/任务/路径覆盖、集成方式/版本与可行性证据。目标提供方属于另一执行模块的写范围时，需登记真实依赖。Implementer/Fixer 提交 reuse_trace，逐映射证明版本、对应 task 文件及绑定证据。verify_plan 在冻结、派发、结果接收、DoD 和审计中检查已选 provider/API/接入证据；未选候选源码变化不单独使消费者失效。OpenSpec reuse.md 与 manifest 暴露当前 plan 的复用映射，冻结前不表示可执行。

完整 Ledger 回归 **133 项通过**（原 120 项 + 11 项复用测试 + 2 项项目上下文测试）。覆盖 TARGET 规划与派发、语义不完整/未评审/未知能力/错误来源、越界 task/PATH 映射、选中版本漂移与未选候选隔离、冻结时版本变化、缺少/版本错误/越界实现绑定拒绝及有效绑定接受、外部 source-module/reference 语义区分、来源模块边界、无候选的新实现、其他 MO 提供方依赖、显式外部来源强制规划，以及配置更新/旧运行隔离/来源错配。所有 11 个技能校验、JSON 模板解析、Python AST 和 git diff --check 通过。四张 SVG/PNG 重新渲染，总览与新增复用图已目视检查。

测试为本地临时目录中的控制器/证据契约回归，未迁移真实业务项目、安装实际二方库或运行设备测试。控制器不会自动提取功能语义、解析包管理器、证明行为等价或提供操作系统级外部写隔离；这些仍由宿主 Agent、项目工具和执行器落实。

## 本轮：上下文就绪落实到控制节点

新增 context_readiness.py 与 context-submit，将上下文核对接入 GO 根登记/覆盖规划、父拆分/GO 接受、子 plan/freeze、Coding/Testing/Fixer assign、Auditor 分析/裁决/最终测试。新 init 默认启用，prepare 强制启用；既有无该字段 run 保留兼容。

完整 **149 项测试通过**（原有 133 项 + 新增 16 项）。新增验证覆盖：

- 缺失报告拒绝登记、规划、Coding/Testing/Fixer 派发、审计分析/裁决及最终审计；不消耗修复预算或推进阶段。
- 实际提交身份、必读引用、草稿绑定与版本检查；较新的 blocked 不能被旧 ready 绕过。
- 证据变更阻止冻结；测试命令替换或环境证据变化在启动子进程前被拒绝。
- 新入口默认启用、prepare 禁止关闭；早于全量收尾的 Auditor 预检被拒绝。
- 父 MO 拆分与 GO 接受、首次 Coding、真实 Main、首轮 Fixer/复测、跨模块 Auditor 修复与正式复核、最终独立审计均走通。
- 无关兄弟的预检/阻塞信息不使当前独立任务失效，不回写兄弟质量。

包级验证：11 个控制器/图集 Python 文件 AST 解析通过、33 个模板/schema JSON 可解析、4 个 SVG 有效、60 个索引与新增协议链接有效；2 个修改的 Skill 通过 quick_validate；git diff --check 通过。四张 SVG/PNG 已重新生成并逐张检查。

验证仅覆盖本地控制器与隔离测试执行器，不代表真实业务工程、设备、宿主自动派发或语义理解质量已验证。宿主仍负责只读预检隔离、身份与工具能力；对应 owner 审核上下文内容是否足够。

## 本轮：功能清单默认来源与完备性

功能列表默认由测试用例汇总抽取；无汇总时先理解存量源码、抽取完整功能，再生成需求/CASE。新增 feature-inventory 模板和 global-plan 的 feature_inventory_ref/feature_owners；GO/父 MO/子规划预检增加 feature-inventory。清单接受后，planning_context 和分配包提供全局清单、归属与各模块 feature_ids；旧运行无清单时保留原上下文结构。

完整 **153 项测试通过**。本轮新增 4 项覆盖：用例汇总优先/源码回退及模块功能列表；未分类、未决、缺少来源/CASE/owner 拒绝；功能疑问必须经真实人工决定后接受；来源证据变化阻止 Coding。既有父子拆分、上下文、修复和审计回归保持通过。

Python/JSON/SVG 解析、相关链接、migration-global Skill 校验及 git diff --check 通过；图集重新生成，总览与子 MO 图已目视检查。验证证明已登记清单的结构/追溯门禁，不证明实际业务源码已被穷尽分析；运行时 Agent 必须逐入口核查，有疑问立即交人工，不得以校验通过宣称无遗漏。

## 本轮：复用必须对齐存量源码并保真复现

全局规范统一覆盖 TARGET 与外部来源的 reuse/adapt/reference。reuse-plan.fidelity 固定 legacy_root、存量源码引用、逐行为对齐报告及 scenario → PATH/ASSERT；新增 reuse-fidelity.md 模板。GO/父 MO 提供源功能上下文，Spec Designer 冻结差异及适配方案，Coding 后 Main 留真实复现记录，MO/Auditor 按原阶段验收；需求冲突仍交人工，Fixer memory 保留源行为、偏差与复测引用。

控制器在 plan 检查存量根与运行一致、源码引用范围及证据、全部映射路径的冻结断言关联；verify_plan 后续检查源码与报告漂移。旧复用计划缺字段需补录/重新冻结。执行证据沿用现有 Main 回执、assert expected/actual、版本和结果链，不增设第二份验收状态。

复用专项 **15 项通过**；完整 Ledger 回归 **157 项通过**。新增 4 项覆盖：reuse/adapt/reference 缺 fidelity 拒绝；错误 legacy_root/提供方冒充存量源码/无源证据拒绝；缺报告、路径/断言错误或缺复现方案拒绝；源码或报告变化后派发拒绝并暴露失效。原接线测试追加正式 Main 结果接受，确认冻结复现路径可按原测试流程记录 Green。模板 JSON、变更 Python AST、协议链接、2 个修改技能 quick_validate 及 git diff --check 均通过。

以上为隔离目录的控制器/契约测试，不代表真实二方库或业务项目已完成保真验证；结构、引用和断言关联不能自动证明语义等价或功能枚举完备。真实场景的源行为分析与生产链路复现仍须运行角色/宿主提供证据。

## 编译构建与自动化拆分（2026-09-19）

Test-Runner 按 build/automation 执行，Fixer 负责修复。新 init 默认、prepare 强制 split_testing_required；冻结两类 PATH，build.command 固定命令及选择依据。新增只读 discover_build 搜索目标脚本，用户命令优先，否则评估 Gradle wrapper/assemble；项目 build 配置和环境文档按 prepare 固化。

构建与自动化分别预检、派发、记录三态并合并结果。新代码使构建失效，构建错误经诊断/Fixer/重建；DoD 检查完整路径。仅自动化环境缺失经 automation-unavailable 进入 automation-deferred，逐路径 Yellow/未执行，不影响可消费当前构建代码的下游。环境恢复使用 automation-resume，不需人工恢复批准；不得借缺环境掩盖当前 Red。

审计缺测保留 unverified_findings，不计 resolved 或 reusable；最终 audit-unavailable 输出 Yellow、completed-with-unverified-tests 并结束本轮。独立 Auditor 实际补测 Green 后可推进模块 DoD，发现实际 Red 则重新进入修复。

完整 **169 项回归通过**。新增 **11 项拆分测试 + 1 项配置快照测试**：构建先于自动化、构建失败及 Fixer 后重建、缺测不伪造 Green/不消费轮次、实际依赖消费者继续、恢复复测链、拒绝隐藏真实失败/其他上下文缺失、审计缺测收尾、独立审计补测后 DoD/发现 Red 后重开、命令发现/用户优先/多根歧义及配置更新隔离。

Python AST、模板/schema JSON、SVG、相关文档链接、3 个修改 Skill 的 quick_validate 及 git diff --check 通过。四张图重新渲染并目视检查，子 MO 图增加自动化环境缺失的独立收尾分支。

测试使用临时 Python 构建/测试进程；未执行用户真实 Gradle 工程或设备业务测试。宿主仍负责真实构建目标/环境、执行隔离、共享资源锁和可信证据。

## Harmony 独立 uv 环境与 CASE 覆盖边界（2026-09-19）

新增独立 pyproject、Python 3.12 版本选择、uv.lock、sandbox.py、公开默认模型配置、无密钥 .env.example 和专用 README。默认模型/endpoint/角色凭证回退取自用户提供的 MobileAgenticOperator；关键 SDK 对齐其版本，依赖从包仓库和已保留的相对路径 wheel 安装，不绑定源项目的机器绝对路径。真实凭证仅复制到 Git 忽略、0600 权限的本地 .env，不进入源码或公开配置。

`uv sync` 已完成实际安装；离线 doctor 中全部 Python 依赖、默认 LLM 配置读取及 PATH 上的 HDC 就绪，未指定 Harmony 设备，因此结果为 Yellow/未执行。general/glm/mcp_agent/hypium_mcp_agent 四种执行器类在新环境中均可加载。未调用真实 LLM、连接设备或执行业务 App。

新增 CASE 门禁：每个模块 CASE 都必须有 automation PATH；build PATH 不能代替业务测试覆盖。Ledger 完整回归 **170 项通过**，包含新增的 build-only CASE 拒绝/补齐后允许检查。Harmony 契约、模拟原生集成与 sandbox 共 **20 项通过**，覆盖环境变量回退/覆盖及脱敏、默认配置、指定 .env 与进程变量优先级、从其他 cwd 使用生成 adapter 且缺设备返回结构化 Yellow、UI 无需 XMind 凭证。

本轮修改保持 SPEC/assignment/host receipt/完整 scope/三态/复测门禁。依赖环境初始化及独立调试不等于模块或全局验收通过；正式测试必须经 Ledger。业务功能与边界枚举仍需角色审核，结构覆盖门禁不证明语义完备。

## 构建、Fixer 与 automation 的宿主衔接（2026-09-19）

将 Test-Runner / MO 角色主步骤和 sdd-module 命令统一为 building 预检 → build assignment → MO 接受全部构建结果 → testing 预检 → 新 automation assignment。双环节协议新增逐节点状态/动作表、模块共享一轮预算、安装包与代码基线证据边界；不增加自动部署或常驻调度服务。

拆分测试 **14 项通过**。扩展原构建修复测试，验证 Ledger 下一步确实在 Fixer 后返回 build，再要求独立 testing 预检并完成 automation/DoD；只有构建通过时修复 memory 仍 awaiting-regression，完整回归通过后才 reusable。新增两项验证：构建已成功但未 accept 时不具备 build_ready、building 报告不能授权 automation；构建已使用一轮 Fixer 后若 automation 失败，下一步为 audit-defer，不能重置本地预算。

本次未改变运行时逻辑；测试使用临时构建/测试子进程，没有运行真实 Gradle 工程或设备 App。

## Auditor 遗留范围与空 global_paths 恢复（2026-09-20）

- 去掉 audit-assign/status 对 global_paths 非空的门禁；原 init=[] 的运行可以继续原事件链，无需重建。
- 最终执行集合从当前非 Green 生成并绑定 assignment.path_ids；宿主执行器拒绝额外 Green PATH。额外声明的运行级路径若未验证/基线失效仍须验证，不能隐式通过。
- 空集合采用独立 audit-review + audit-verdict 上下文门禁，必须有审阅证据；不运行自动化、不伪造测试结果。旧全量 assignment 先停止/撤销后重派。
- 缺测补验合并结果，保留已有构建 Green；跨模块修复仍依据 finding/owner/依赖图做受影响模块回归，一轮失败转人工。
- Ledger **178 项通过**；新增空 init 审阅、空 init 跨模块修复/失败人工、Red/Yellow 选集与拒绝空审阅掩盖问题、缺测补验保留构建、有效全局 Green 复用及失效复测链等验证。
- Harmony **20 项通过**（测试替身，不代表真实设备/LLM 测试）。技能校验、Python AST、JSON、文档链接及 git diff --check 通过；三张受影响流程图已重新生成并目视检查。

## 父 MO 命名与 GO 用例报告（2026-09-20）

- 父名称统一 parent-mo-M<编号>，从待拆根模块到父汇总/冷恢复保持一致；status.parent_mo_names 与父 next_step.agent_name 提供宿主信号，父 session 自动补全名称并拒绝显式错名。不更改冻结分配包或真实实例身份。
- Ledger 自动投影 reports/migration-report.md/json，status 返回绝对路径及 sequence；GO 收尾展示全部 CASE 状态、PATH 明细与非 Green 根因/证据。
- 报告保留未规划/未运行/自动化缺测；过期 Green 降为有效 Yellow并保留历史值。当前 Auditor 结果可覆盖旧模块结果，空 audit-review 沿用真实 CASE 证据，不生成假测试。构建 Green 不掩盖业务缺测；跨模块 CASE 聚合失败不覆盖无关已通过路径。
- Ledger **188 项测试通过**，其中新增 10 项覆盖名称/会话恢复、完整 Green、Red 断言与引用、缺路径/缺测、代码过期、Auditor 补验/空审阅、共享 CASE 聚合和人工审核证据。技能校验、Python AST、文档链接与 git diff --check 通过。验证使用隔离临时运行及测试执行器，不代表完成真实项目迁移或设备测试。
# 审计构建与自动化异常闭环（2026-09-22）

按用户批准修复三项复审发现：

- Auditor 批次的构建 Red/Yellow 经 accept 进入 build-verification-failed，报告保留结果引用与编译/超时根因，仅关联分支等待人工；独立分支继续。构建 Green 仍须 Automation，不生成自动化通过证明。
- execute_test 在原 attempt 留存并绑定 partial_observations_ref。harmony_stage 与 Ledger 验收共用 test_completion.interpret：完整失败报告后超时仍保留失败 ASSERT、原根因分类和退出异常；部分观测恢复为 Yellow，混合 pass/fail 保留失败和 flaky。不能把已观察失败改成纯环境缺测，不能由不完整完成记录得到 Green。
- 原结果 JSON 截断、编码或格式错误转为有证据和解析原因的 Yellow，submit/accept 后关闭 assignment；原 result/observations 不改写。身份/query/hash/媒体不匹配仍拒绝，验收重新计算派生结果。

新增 **11 项**真实子进程/状态机回归：完整失败后超时、部分失败与混合重试、成功报告后超时不得 Green、截断 JSON 关闭 assignment、错误 JSON 形状、回执身份/原件 hash 篡改拒绝、部分媒体篡改拒绝、审计构建 Red/Yellow 人工出口、Green 构建继续自动化、独立审计分支保持可执行。

全套 **465 项通过**：Ledger 295（82.096 秒）、适配器 42（2.085 秒）、Harmony 内核 128（0.95 秒），无失败/跳过。静态检查：144 个 Python AST、42 个 JSON、91 个 vendored 文件摘要及 git diff --check 通过。测试使用既有 Python 3.12、只读 pytest，禁用字节码和 pytest 缓存；本机 loopback 租约测试获准执行，不连接外部设备或模型。原生测试须将 Harmony 根加入 import path；初次收集缺少该路径，修正启动参数后全部通过，未安装依赖。

未执行真实移动设备、LLM 或业务 Gradle。既有原生测试夹具仍有 engine.log 未关闭 ResourceWarning；不影响断言结果。隔离夹具按 cleanup 清理，修改集中于本包控制器、测试和协议说明；未提交或推送 Git。

---
