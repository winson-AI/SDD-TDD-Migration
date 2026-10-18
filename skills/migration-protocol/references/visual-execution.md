# 受限视觉执行工具

本入口补充设备与比较取证。GO/父子 MO、冻结、验收与独立审计沿现有流程，工具不提交 Ledger、不修代码、不自行增加比较或修复轮次。

## 1. 准备与冻结

1. Host/Test-Runner 按项目参考配置（可存 `.sdd-migration/harmony/visual.json`）或 [配置模板](../../../template/visual-execution.json)，在本轮 `runs/harmony/sandbox/environment/visual.json` 生成执行配置；与 sandbox 的 config.json 分开，执行期间不改写。只复制本次选定的设备/backend/模型配置，不假定本机默认设备。
2. Spec/Test design 把 `visual_execution` 放到对应 automation/visual PATH：environment_ref 的真实 path/hash、app_id、导航 actions、目标选择器；随路径冻结，变更走 CR/重新冻结。无视觉需求时不加此字段。
3. 设备执行用显式 HDC 或 adb backend（Android 目标装 APK，`ability` 填 activity，装机后在设备上核对包哈希）；模型用显式启用的 external 配置，API key 只从指定环境变量读取，配置与请求只存变量名，不归档 `.env` 或明文 key。
4. 执行前 Host 持有设备独占锁并在认证 host-context 注入 device_lock（device_id、assignment_id、fencing_token、held）；Agent 自填的锁字段不算锁。

## 2. 执行节点

操作都经 [lean_worker.py](../../migration-ledger/scripts/lean_worker.py)，请求样式见 [visual-request.json](../../../template/visual-request.json)，每次新 request_id：

```sh
python3 <package_root>/skills/migration-ledger/scripts/lean_worker.py \
  --root <run_root> --request <request.json> --host-context <authenticated-host.json>
```

| operation | 所需状态与输入 | 输出意义 |
| --- | --- | --- |
| visual-install | 当前 build 已接受 Green；automation 或 visual assignment；path_id、该 PATH 已接受构建的 artifact_ref | 校验包身份、实际安装并记录装机元数据和命令；INSTALLED 不是测试通过 |
| visual-capture | 当前功能 Green 后的 visual assignment；冻结目标、artifact_ref、同 assignment/fence 的 install_ref、reference_manifest_ref、正整数 round | 真实截图/XML/meta/manifest，绑定构建、设备、状态与轮次；CAPTURED 不是视觉对齐通过 |
| compare-only | visual assignment；实际 reference_ref/candidate_ref | 确定性 score；不能直接给 ALIGNED |
| semantic-inspect | visual assignment；冻结配置、reference_ref/candidate_ref/score_ref | 有总时限的模型比较，保留图片对与 score hash；INSPECTED 不是裁决 |
| image-parity | visual assignment；path_id、已完成候选 capture 的 manifest_ref 与 round；PATH 携带冻结的 image_checks | 逐检查在目标 view tree 定位节点、裁剪并与参考栅格比较，写 image-parity.json；MEASURED 是测量不是裁决，验收时重算 |
| legacy-capture | Spec-Designer/Test-Runner 当前 assignment；存量预览为 adb 设备或 browser，宿主锁住该设备 | 见 [存量捕获](#4-存量捕获) |

带 `image_check_ids` 的 PATH：visual-install → visual-capture → `image-parity` → adapter 的 `--image-parity`；图片、文本与节点检查出自同一次 capture。无 `baseline_ref` 时 visual-capture 不需要 reference_manifest_ref；带基线的 PATH 同时承载检查时较弱的结果决定三态。报告须属于当前 assignment、代码基线、HAP 与所选 capture。

叶子 PATH 的比较原图都来自同 coverage 的冻结 UI evidence（baseline_refs/capture_manifest_ref），含滚动目标的后续截图；不能借含首屏的任意 manifest 添加基线。user-reference PATH 的 reference manifest 由 Test-Runner 以用户截图构造 android-reference 记录，截图集合恰为 baseline_refs。Auditor 读原叶子 SPEC 的证据集合，不按构建归属猜 UI 归属。GLOBAL 自有 PATH 用 visual_evidence 显式冻结 coverage、visual_mode、capture_manifest_ref 与完整 baseline_refs；缺完整原始证据保留局部 Yellow，adapter 不能提升为 Green。

visual-capture 把 capture_execution_ref 写入候选 snapshot（[捕获执行回执](../../../template/visual-capture-execution.json)）；adapter 与正式验收重读本 run 的安装回执、执行日志、截图/树和元数据推导 capture_evidence，检查 HAP/代码及完整原图集合。外部捕获器须提供同契约 sidecar（成功安装命令、实际 capture 命令与图片输出，meta 的构建/代码字段一致），缺 sidecar 保留 Yellow；carried 只重验实际引用的历史轮次。

安装可在功能自动化前执行；换 assignment 后须有当前授权的装机证据。`execute_test` 把当前 assignment_id/fencing_token 写入 visual query 的 `execution_assignment`，最新 capture_execution 须属于该授权，正式 submit/accept/Auditor 以 Ledger 的 assignment 再核验；HAP 与代码未变，新审计任务也须重新捕获（重读旧截图只是审阅），ALIGNED_CARRIED 引用的历史轮次可保留旧授权。最终 Auditor 只处理选取的审计 PATH，设备工具校验当前审计快照与 PATH 所属构建产物。

viewport 捕获要求实际前台 App、冻结目标选择器与截图前后稳定的树。scroll 还需有源码依据的终点选择器 `scroll_end_match` 与唯一 `scroll_region`，连续保存每屏并有界滚动，实际观察到终点才算 scroll-complete；多滚动区域拆 PATH 或用既有完整 adapter。无可信区域、未到终点、状态变化、截断或重复画面都不证明完整覆盖，保留 partial/Yellow，缺 scrollable 节点不等于无须滚动。模糊导航/未支持 backend 用正式运行器或如实留缺口。

失败归类：候选 App 启动后从运行列表消失是代码缺陷，worker 返回 `FAILED` / `app-runtime-failure`，Test-Runner 记 Red 进诊断；App 仍在运行但不在前台是 `target-precondition` 的 Yellow。只读查询遇瞬时超时重试一次，动作不重复；树里找不到控件只是取证不充分。

Test-Runner 把原始截图、score、semantic 与交互证据组装成 alignment 结构，经 `execute_test.py → lean_visual_adapter.py → tests submit/accept` 正式复核；脚本不从分数推导 ALIGNED，冻结手势仍需实际 action/observation 证据，本入口不执行未声明手势，不代替功能自动化 Main。

semantic 原文件的所有 issues 及 `comparability < 0.4` 或 `comparable=false` 都须在对应 comparison 的 `semantic_dispositions` 逐项裁决才可声明 Green；0.4 只标记待解释矛盾，不是通过阈值。每项含原 semantic_ref（path/hash）、原 finding（issue 含 index 与完整内容）、`resolved|dismissed`、非空 reason 和至少一份不同于原 semantic 的 evidence_refs；无问题不制造裁决。正式门禁重读原件，漏项、重复、旧 hash 或只有结论没证据均拒绝；示例见 [visual-alignment.json](../../../template/visual-alignment.json)。裁决由当前测试/审计 Agent 作出，工具不替 Agent 判断。

## 3. 失败、留存与恢复

每个请求的 request/result/receipt、设备命令、装机结果、截图/树/meta/manifest、比较结果放 `runs/harmony/sandbox/<actor>/<request_id>/`；正式测试回执与报告仍在 `runs/harmony/automation/<attempt>/`。配置归同 run 的 sandbox/environment；正常临时文件清理，无法清理时保留原因。设备临时截图/树仅删除本次生成的文件，失败留清理记录。

工具 BLOCKED/quality_candidate 只是待提交证据，不能直接改 Ledger。缺少工具、设备、模型或观测条件时，Test-Runner 留原因/日志，MO 按实际情况使用既有 Yellow/未执行与 automation-unavailable 通道。已经观察到的失败断言不能覆盖成缺环境；设备错误或页面不符也不自动断言为实现缺陷，先走现有根因判断。

工具执行取消后由宿主核实停止，按已有 revoke/audit-revoke 处理，不重启或释放业务锁。配置/hash/assignment/权限不匹配属于受控拒绝，返回原因供相关 owner 修订，不转换为测试 Green。真实设备与模型能力须在项目环境验证，本包的隔离测试仅证明控制与证据契约。

## 4. 存量捕获

存量可跑时，Spec-Designer 在 analyze-ui 前用 `legacy-capture` 捕获本叶 UI 项的 page:state:coverage；步骤给出 `capture_due`（尚无 runtime 证据的条目与最近一次捕获的 manifest），请求见 [legacy-capture-request.json](../../../template/legacy-capture-request.json)。adb 后端按声明装机、启动、走冻结 tap/swipe/back、核对前台与选择器，截图前后树稳定才写参考记录；动作写不成确定性步骤的目标带 `navigation: {mode: agent, steps}`，由声明的 `legacy_preview.navigator`（adapter 的 snapshot 任务）走到界面，到达后仍按冻结选择器捕获，未到达记 `navigation-unverified` 并附 capture_gap 建议；browser 后端用 Playwright 打开 url、走冻结 click、DOM 转树并按同一滚动契约滚到冻结终点，记 legacy-reference/web；其 UI 树由 analyze-ui（platform=web）从运行时索引派生，无源索引，节点 id 取元素 id，图片来源只记录。捕不到的目标带原因（PARTIAL/BLOCKED），写入 `capture_gap`；manifest 作 analyze-ui 的 capture_ref 与 runtime 证据，CAPTURED 不是对齐通过。
