"""Render automation contracts and the Harmony inner loop; no runtime changes."""
from generate_workflows import Diagram, COLORS, TINTS


def artifact(d, x, y, w, h, title, body=()):
    d.lines.append(f'<path d="M{x+18},{y} H{x+w} L{x+w-18},{y+h} H{x} Z" '
                   f'fill="{TINTS["gray"]}" stroke="{COLORS["gray"]}" stroke-width="1.7"/>')
    top = y + (h - (32 + len(body)*29))/2 + 24
    d.text(x+w/2, top, title, 25, weight=650, width=w-30)
    for i, line in enumerate(body):
        d.text(x+w/2, top+34+i*29, line, 21, '#4b5563', width=w-30)


def automation_flow():
    d = Diagram('automation-flow', 2850, '05', 'Automation · 输入、执行与验收闭环',
                '构建是前置门禁；每条 PATH 独立执行；环境缺测不传播失败，完整 Green 才能验收通过')
    artifact(d, 460, 190, 640, 130, '测试输入 → 冻结 PATH',
             ['SPEC / CASE → PATH ID + Name / 参数 / 步骤 / ASSERT', '测试设计先完成；冻结后禁止自行放宽预期'])
    d.box(60, 190, 340, 210, '项目上下文',
          ['存量 / 目标 / 架构 / 测试', '二方库行为对齐与 fidelity', 'adapter + 环境 / fixture', '项目配置 → 本轮快照'], 'gray')
    d.arrow([(400, 255), (460, 255)])
    d.arrow([(780, 320), (780, 375)])
    d.box(460, 375, 640, 115, 'Coding 接受 → 当前 build Green',
          ['编译失败先诊断 / Fixer；新代码必须重新构建', '构建通过不代表任何业务 CASE 已通过'])
    d.arrow([(780, 490), (780, 550)])
    d.box(460, 550, 640, 140, 'Test-Runner · testing 预检',
          ['冻结规格 / 路径 / 代码 / 提供方 / 环境 / 权限', '提交 context-submit；绑定实际 argv / cwd / 环境', '宿主负责实际启动、角色身份和资源锁'], controller=True)
    d.arrow([(780, 690), (780, 735)])
    d.diamond(780, 800, 330, 130, '预检结果', '是否具备执行条件')
    d.arrow([(615, 800), (400, 800)], 'orange'); d.label(505, 780, '其他缺项', 'orange')
    d.box(60, 745, 340, 145, '补齐相关上下文',
          ['仅阻塞相关模块阶段', '不派发 Main，不制造结果', '无关 MO 继续'], 'orange')
    d.arrow([(945, 800), (1160, 800)], 'orange'); d.label(1045, 780, '仅环境缺失', 'orange')
    d.box(1160, 725, 380, 230, 'MO · 缺测旁路',
          ['automation-unavailable', '→ automation-deferred', '逐 PATH：Yellow / 未执行', '保留 build Green，不耗修复轮次', '不能掩盖已观察到的 Red'], 'orange', True)
    d.arrow([(780, 865), (780, 940)]); d.label(780, 910, 'ready')
    d.box(460, 940, 640, 125, 'assignment → 宿主 execute_test',
          ['scope=automation；重验代码 / 环境 / 命令', '每条 PATH 新目录 + 新进程；写完整 query.json'])
    d.arrow([(780, 1065), (780, 1120)])
    d.box(460, 1120, 640, 145, '逐 PATH 调用项目 Main',
          ['argv + --query-file … --result-file …', 'Harmony：Planner / Executor / Verify（图 06）', '其他平台：项目真实 adapter'], controller=True)
    d.box(60, 1080, 340, 190, '两层执行结果',
          ['包装器 exit 0：已写回执', '不等于 CASE 通过', '超时 124 / 启动失败 127', '以 receipt / assertions 为准'], 'orange')
    d.arrow([(780, 1265), (780, 1320)])
    artifact(d, 460, 1320, 640, 130, '单路径执行工件',
             ['result.json + 日志 / 媒体 / observations', 'receipt.json：身份 / 时间 / argv / 退出码 / hash'])
    d.arrow([(780, 1450), (780, 1505)])
    artifact(d, 460, 1505, 640, 125, '汇总 stage-result.json',
             ['本 assignment scope 的所有 PATH 均须记账', '每条：三态 / ASSERT / 根因 / receipt / retest_of'])
    d.arrow([(780, 1630), (780, 1685)])
    d.box(460, 1685, 640, 140, 'Ledger submit → owner 接受',
          ['两次核对版本 / 覆盖 / 回执 / 断言 / 证据摘要', '模块 CASE：MO；审计 CASE：Auditor', '缺证据或不匹配被拒绝，不能按通过处理'], controller=True)
    d.arrow([(780, 1825), (780, 1875)])
    d.diamond(780, 1940, 330, 130, '正式三态', '以本次证据为准')
    d.arrow([(615, 1940), (400, 1940)], 'green'); d.label(505, 1920, 'Green', 'green')
    d.box(60, 1870, 340, 170, 'MO · 完整 DoD',
          ['build + automation 全覆盖', '当前基线全部 Green', '任务追溯 / checklist 完整', '记录模块通过'], 'green', True)
    d.arrow([(945, 1940), (1160, 1940)], 'orange'); d.label(1045, 1920, 'Red / Yellow', 'orange')
    d.box(1160, 1855, 380, 180, '诊断 → 修复路由',
          ['可修复：本地先一轮 Fixer', '补丁接受 → 重建 → 正式复测', '依赖 / 外围 / 仍失败：留证', '待统一 Auditor，不终止兄弟'], 'purple')
    d.box(1160, 1505, 380, 170, '修复返回 B',
          ['入口 B = Coding 接受 / build', '新 code_baseline，旧构建失效', '保留失败与 repair memory', '复测必须关联 retest_of'], 'purple')
    d.arrow([(1350, 1855), (1350, 1675)], 'purple'); d.label(1350, 1770, '修复获接受', 'purple')
    d.label(1045, 360, '入口 B', 'purple')
    d.box(1160, 1020, 380, 190, '环境恢复返回 A',
          ['新 testing ready 报告', 'automation-resume → 新派发', '入口 A = testing 预检', '不额外要求人工恢复批准'], 'purple')
    d.arrow([(1350, 955), (1350, 1020)], 'purple', dashed=True)
    d.label(1045, 535, '入口 A', 'purple')
    # Join settled paths only, routing outside the central execution column.
    d.arrow([(230, 2040), (230, 2170), (780, 2170)], end=False)
    d.arrow([(1350, 2035), (1350, 2170), (780, 2170)], 'orange', end=False)
    d.label(1350, 2100, '遗留已留证', 'orange')
    d.arrow([(1540, 840), (1570, 840), (1570, 2170), (1350, 2170)], 'orange', dashed=True, end=False)
    d.arrow([(780, 2170), (780, 2230)])
    d.box(460, 2230, 640, 130, '父汇总 → GO 全量收尾门禁',
          ['全部叶子本轮结束，全部父汇总当前有效', '无 worker / ready 动作，才统一启动 Auditor'], 'orange', True)
    d.arrow([(780, 2360), (780, 2410)])
    d.box(460, 2410, 640, 150, 'Auditor · 独立闭环',
          ['实际遗留：SPEC / PATH → 根因 → Fixer → Testing', '裁决失败：结构化根因待人工；缺环境保留未验证', '最终固定快照，覆盖 global + module PATH'], controller=True)
    d.arrow([(780, 2560), (780, 2620)])
    artifact(d, 300, 2620, 960, 125, '最终输出：通过 / 问题待决 / 缺测清单',
             ['全覆盖真实 Green 才通过；纯缺环境可 completed-with-unverified-tests（Yellow）', '模块原始结果、审计结果与历次失败均保留；收尾不等于验证通过'])
    d.legend(2800)
    d.save()


def automation_engine():
    d = Diagram('automation-engine', 2230, '06', 'Harmony · 单 PATH 自动化内核',
                '内核属于同一次 Test-Runner 执行；只负责设备操作与断言取证，不承担外层修复或验收权限')
    artifact(d, 440, 190, 720, 130, '完整 query + 引擎配置',
             ['冻结步骤 / 参数 / ASSERT / after_step / 当前代码身份', '设备 / 三类模型 / 预算 / 可选 knowledge_ref 与 recording_ref'])
    d.arrow([(800, 320), (800, 375)])
    d.box(440, 375, 720, 125, 'adapter 校验与隔离',
          ['验证字段与引用 hash → 设备互斥锁 → 本次独立目录', '注册 Verify wrapper；加载技能 / 自定义工具'])
    d.arrow([(800, 500), (800, 555)])
    d.box(440, 555, 720, 110, 'task_text：步骤与冻结断言交错',
          ['每条 verify 使用单个 [ASSERT:id]；知识只辅助执行'])
    d.arrow([(800, 665), (800, 715)])
    d.diamond(800, 780, 330, 130, '显式录制？', 'hash / 任务文本须匹配')
    d.arrow([(635, 780), (380, 780), (380, 880)]); d.label(490, 760, '无录制')
    d.arrow([(965, 780), (1220, 780), (1220, 880)]); d.label(1100, 760, '有效录制')
    d.box(80, 880, 600, 140, 'Planner → Executor',
          ['Observe → 单步工具 / execute → 实际反馈', 'general / glm / MCP / Hypium MCP', '压缩上下文 / 可选反思 / 技能 / XPath 缓存'], controller=True)
    d.box(920, 880, 600, 140, 'ToolPlayer · 导航回放',
          ['坐标 / XPath / 输入 / 进度条 / 临时控件', '意外弹窗处理；验证不复用旧通过结果', '失败时携带历史，在剩余预算内重规划'], controller=True)
    d.label(580, 865, '入口 C', 'purple')
    d.label(1420, 865, '入口 D', 'purple')
    d.arrow([(920, 950), (680, 950)], 'purple'); d.label(800, 930, '失败重规划', 'purple')
    d.arrow([(380, 1020), (380, 1070), (800, 1070)], end=False)
    d.arrow([(1220, 1020), (1220, 1070), (800, 1070)], end=False)
    d.arrow([(800, 1070), (800, 1130)])
    d.box(440, 1130, 720, 120, '到断言时机 → Verify wrapper',
          ['ASSERT ID 找回冻结谓词与 matcher，防止改写期望', '固定 verification 强制保留；auto 才动态选择'])
    d.arrow([(800, 1250), (800, 1300)])
    d.box(440, 1300, 720, 135, '真实媒体验证',
          ['单图 / 双图 / 跨步骤 / 参考图 / 视频', '时间线取证；视频录制 / 时间映射 / 裁剪 / 压缩', '输出布尔结果 + 原始理由 + 实际工具 + 媒体引用'])
    d.arrow([(800, 1435), (800, 1485)])
    artifact(d, 440, 1485, 720, 120, 'ObservationSink · 每次立即落盘',
             ['sequence / ASSERT ID / result / reason / tool / error', 'evidence_refs = 实际媒体路径 + SHA256'])
    d.box(80, 1270, 290, 195, '继续原执行分支',
          ['Planner 返回 C', 'ToolPlayer 返回 D', '仍受步骤 / 超时预算限制', '禁止重启或放宽验收'], 'purple')
    d.arrow([(440, 1545), (225, 1545), (225, 1465)], 'purple')
    d.box(1230, 1270, 310, 235, '留存全部证据',
          ['截图 / 布局 / 视频', '原生 HTML / MD / JSON', 'engine.log / 工具时间线', '候选录制与执行记忆', '不是已验证的修复 memory'], 'gray')
    d.arrow([(800, 1605), (800, 1675)]); d.label(800, 1648, '完成 / 异常 / 预算耗尽')
    d.box(440, 1675, 720, 170, 'report() · 汇总全部观察',
          ['Yellow 优先：缺断言 / 媒体 / 异常 / 歧义 / flaky', '无阻断但有有效 false → Red；完整 true → Green', '保留失败观察；同 ASSERT 混合 pass/fail 不挑最好一次', 'final_output 文本不能生成通过结论'], controller=True)
    d.arrow([(800, 1845), (800, 1900)])
    artifact(d, 440, 1900, 720, 145, 'result.json → 宿主 receipt → tests stage',
             ['quality / assertions / root_cause / flaky / 上下文身份', '观察 / 环境 / 全部工件 / 源快照引用', '交 Ledger 校验，MO 或 Auditor 按阶段验收'])
    d.text(800, 2110, '时序和 exact 仍含模型判断；宿主需提供真实 App 安装与环境证据，文件摘要不能代替真机验证。', 21, '#4b5563')
    for i, (key, label) in enumerate([('blue', '执行 / 证据'), ('orange', '条件判断'), ('purple', '恢复 / 继续')]):
        x = 65 + i*280
        d.arrow([(x, 2180), (x+48, 2180)], key)
        d.text(x+60, 2187, label, 19, '#6b7280', anchor='start')
    d.text(1535, 2187, '内核内部调用；跨编排角色的交接才经 Ledger', 18, '#6b7280', anchor='end')
    d.save()


if __name__ == '__main__':
    automation_flow()
    automation_engine()
