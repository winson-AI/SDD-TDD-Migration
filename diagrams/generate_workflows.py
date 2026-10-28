"""Render the documented migration workflow as SVG and PNG (requires rsvg-convert)."""
from html import escape
from pathlib import Path
import subprocess
import unicodedata

OUT = Path(__file__).resolve().parent
COLORS = {'blue': '#2563eb', 'orange': '#ea580c', 'green': '#059669',
          'purple': '#7c3aed', 'gray': '#6b7280'}
TINTS = {'blue': '#eff6ff', 'orange': '#fff7ed', 'green': '#f0fdf4',
         'purple': '#faf5ff', 'gray': '#f9fafb'}


class Diagram:
    def __init__(self, name, height, number, title, subtitle):
        self.name, self.height = name, height
        self.lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{height}" viewBox="0 0 1600 {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title>', f'<desc id="desc">{escape(subtitle)}</desc>',
                      '<style>text {font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", "Microsoft YaHei", sans-serif;}</style>', '<defs>']
        for key, color in COLORS.items():
            self.lines.append(f'<marker id="arrow-{key}" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,4 L0,8 Z" fill="{color}"/></marker>')
        self.lines += ['</defs>', f'<rect width="1600" height="{height}" fill="white"/>']
        self.text(60, 56, f'{number}  /  SDD-TDD-Migration', 21, '#6b7280', anchor='start')
        self.text(60, 108, title, 38, anchor='start', weight=700)
        self.text(60, 145, subtitle, 21, '#6b7280', anchor='start')

    def text(self, x, y, label, size=22, color='#111827', anchor='middle', weight=400, width=None):
        units = sum(1 if unicodedata.east_asian_width(c) in 'WF' else .57 for c in label)
        if width:
            size = min(size, (width-30) / max(units, 1))
            assert size >= 17, f'Text too dense: {label}'
        self.lines.append(f'<text x="{x}" y="{y}" font-size="{size:.2f}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}">{escape(label)}</text>')

    def box(self, x, y, w, h, title, body=(), color='blue', controller=False):
        self.lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{TINTS[color]}" stroke="{COLORS[color]}" stroke-width="1.7"/>')
        if controller:
            self.lines.append(f'<rect x="{x+5}" y="{y+5}" width="{w-10}" height="{h-10}" rx="10" fill="none" stroke="{COLORS[color]}" stroke-opacity="0.28"/>')
        top = y + (h - (32 + len(body)*29))/2 + 24
        self.text(x+w/2, top, title, 26, weight=650, width=w)
        for i, line in enumerate(body):
            self.text(x+w/2, top+34+i*29, line, 22, '#4b5563', width=w)

    def band(self, x, y, w, h, title, hint=''):
        self.lines.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="20" fill="none" stroke="#d1d5db" stroke-width="1.4"/>')
        self.text(x+24, y+39, title, 24, anchor='start', weight=650)
        if hint:
            self.text(x+w-24, y+39, hint, 19, '#6b7280', anchor='end')

    def arrow(self, points, color='blue', dashed=False, end=True):
        path = points if isinstance(points, str) else 'M'+' L'.join(f'{x},{y}' for x,y in points)
        self.lines.append(f'<path d="{path}" fill="none" stroke="{COLORS[color]}" stroke-width="2.2" stroke-linejoin="round"'+
                          (' stroke-dasharray="7 5"' if dashed else '')+
                          (f' marker-end="url(#arrow-{color})"' if end else '')+'/>')

    def label(self, x, y, label, color='gray', size=20):
        w = sum(1 if unicodedata.east_asian_width(c) in 'WF' else .57 for c in label)*size+18
        self.lines.append(f'<rect x="{x-w/2}" y="{y-size}" width="{w}" height="{size+9}" rx="4" fill="white" opacity="0.97"/>')
        self.text(x, y, label, size, COLORS[color])

    def diamond(self, x, y, w, h, title, sub=''):
        self.lines.append(f'<path d="M{x},{y-h/2} L{x+w/2},{y} L{x},{y+h/2} L{x-w/2},{y} Z" fill="{TINTS["orange"]}" stroke="{COLORS["orange"]}" stroke-width="1.8"/>')
        self.text(x,y if sub else y+8,title,24,weight=650)
        if sub:
            self.text(x,y+29,sub,19,'#6b7280')

    def legend(self, y):
        for i, (key, label) in enumerate([('blue','流程推进'),('orange','条件 / 阻塞'),('purple','修复 / 恢复')]):
            x=65+i*280
            self.arrow([(x,y),(x+48,y)],key)
            self.text(x+60,y+7,label,19,'#6b7280',anchor='start')
        self.text(1535,y+7,'所有交接均通过 Ledger；箭头不表示 Agent 私聊',18,'#6b7280',anchor='end')

    def save(self):
        self.lines.append('</svg>')
        svg = OUT / f'{self.name}.svg'
        svg.write_text('\n'.join(self.lines)+'\n')
        subprocess.run(['rsvg-convert', str(svg)], stdout=subprocess.DEVNULL, check=True)
        subprocess.run(['rsvg-convert', '-w', '1920', str(svg), '-o', str(svg.with_suffix('.png'))], check=True)
        print(svg.name, '→', svg.with_suffix('.png').name)


def overview():
    d=Diagram('workflow',2320,'01','三层编排 · 迁移总览','scope / 全量 CASE → TASK / 四维 → SPEC 冻结 → 任务执行与反馈调整 → 统一宿主 Auditor')
    d.box(100,190,1020,140,'用户输入 → 项目上下文固化',[
        '规范 / 新架构 / 存量与目标代码 / 知识（文件或 wiki 目录）/ 测试用例 / 复用来源 / 参考截图与录屏',
        'init 前一次问完：存量怎样跑、目标在哪预览、资源怎样进目标、范围、依赖授权；prepare 固化快照、适配器与存量提交'], 'gray')
    d.arrow([(610,330),(610,425)])
    d.band(60,365,1100,230,'GO  ·  全局规划','全局管理迁移、DAG、锁与依赖')
    d.box(100,425,1020,165,'GO · 功能覆盖 → 划 scope / 分配全量 CASE',[
        '有用例：用例范围界定叶子；无用例：读源码建功能树再派生用例',
        'TARGET 画像（无 / 壳 / 部分 / 已有，target-scan 给候选）+ 二方库：reuse-catalog / 语义',
        '先分配 scope / CASE；四维形式化业务、功能与代码边界',
        'project / single-module 同一主线；叶子 = 功能树上的子业务流'],controller=True)
    # Fan out through a shared branch; two parents show project multiplicity.
    d.arrow([(610,590),(610,690)],end=False)
    d.arrow([(340,690),(880,690)],end=False)
    for x in (340,880): d.arrow([(x,690),(x,700)])
    d.band(60,635,1100,265,'父 MO  ·  认领与拆分','每个父 MO 持续看护自己认领的整个模块')
    d.box(100,700,480,170,'父 MO · 根模块 A',[
        '认领模块 / 实现 / 四维上下文', 'Ledger 起草切分；3–30 CASE，<6 不拆；页面是 TASK', '子四维、行为评审与用例验收由 Ledger 补齐', '可不全覆盖：漏掉的记欠项，首版后补齐'],controller=True)
    d.box(640,700,480,170,'父 MO · 其他根模块 × N',[
        'project 按根模块分别建立父 MO', '子 scope / CASE；功能叶不重叠，横切功能随主流程叶', '继承实现 / 复用 / 四维上下文', 'single-module 仅保留选定根模块'],controller=True)
    # Anchor branch endpoints to the cards (container crossings remain open).
    for x in (340,880):
        d.arrow([(x,870),(x,940),(610,940)],end=False)
    d.arrow([(610,940),(610,980)])
    d.box(100,980,1020,110,'接受拆分 → 登记子模块 → 全局覆盖',[
        'Ledger 起草的切法当场接受、覆盖沿用；登记已说明覆盖（含功能归属）时由 Ledger 起草；其余 GO 审核'])
    d.arrow([(610,1090),(610,1220)],end=False)
    d.arrow([(215,1220),(1010,1220)],end=False)
    d.band(60,1170,1100,265,'子 MO  ·  任务规划与独立执行','单个失败不取消或污染无关子模块')
    for x,title,subtitle in [(100,'子 MO · A1','子 scope A1'),(365,'子 MO · A2','子 scope A2'),(630,'子 MO · B1','子 scope B1'),(895,'子 MO · B…','其他子 scope')]:
        cx=x+115
        d.arrow([(cx,1220),(cx,1240)])
        d.box(x,1240,230,165,title,['TASK / 四维 → SPEC','MO 审核冻结','实现→测试→反馈调整','DoD / 明确挂起'],controller=True)
    for centers,summaryx in [((215,480),100),((745,1010),640)]:
        for cx in centers: d.arrow([(cx,1405),(cx,1480)],end=False)
        d.arrow([(centers[0],1480),(centers[1],1480)],end=False)
        d.arrow([(sum(centers)/2,1480),(sum(centers)/2,1520)])
        d.box(summaryx,1520,480,115,'对应父 MO 汇总',[
            '孩子首版收尾后补齐漏掉的覆盖','module-summary 绑定当前子状态'])
    for x in (340,880): d.arrow([(x,1635),(x,1670),(610,1670)],end=False)
    d.arrow([(610,1670),(610,1710)],'orange')
    d.box(100,1710,1020,140,'GO · 全量收尾门禁',[
        '所有子 MO：DoD 完成 / 自动化缺测已记录 / 其他问题明确挂起',
        '所有父汇总有效；无活动 worker，也无可推进 / 恢复动作'], 'orange',True)
    d.arrow([(610,1850),(610,1910)])
    d.box(100,1910,1020,110,'统一 Auditor · 代码治理 → 遗留复核',[
        '先审查改动 / 冗余 / 二方库 / 公共能力；委派治理后再处理 Red / Yellow',
        '纯自动化缺环境：保留未验证清单，其他可执行任务继续；收尾复盘由 Ledger 起骨架派它，不阻塞交付'])
    d.arrow([(610,2020),(610,2080)])
    d.box(100,2080,1020,125,'独立审阅收尾 → 全局报告',[
        '只复核遗留 / owner 代码变动的路径；波次集成已跑的不重跑',
        '全通过才 Green；仅缺自动化环境：Yellow / 未执行报告，本轮可结束'], 'green')
    # Shared planes: explanatory cards, deliberately not direct agent channels.
    d.box(1210,190,330,280,'全局读取视野',[
        'GO / 父 MO / 子 MO', '均可读全局存量与目标代码', '架构 / 知识文档 / 分工 / 复用来源', '缺的知识登 knowledge-need，人补充', '局部 context pack 聚焦任务', '不截断全局只读上下文'], 'gray')
    d.box(1210,540,330,270,'范围逐层细化',[
        'GO → 根模块 scope', '父 MO → 子模块 scope', '子 MO → tasks + 冻结测试源', '依赖方并行规划，代码等提供方首版', '起步门禁即冻结；design 按需', '真实未决 / 语义授权变化交人工'], 'orange')
    d.box(1210,880,330,310,'Ledger · 唯一总线',[
        '分配包 / 事件 / 状态 / 证据', 'planning_context：全局视野', 'wave-complete：派波次集成', '预检：Ledger 代写或骨架起笔', '已有事实代填；被拒列全问题', '就绪才开工，阻塞退回派发前', '父聚合颜色不回写子模块'], 'green')
    d.box(1210,1230,330,290,'宿主执行层',[
        '实际派发执行角色并绑定身份', 'worker 只读本步阅读卡', '同 Run：Fixer / CR / 父 MO / GO', 'drive：并行限预算，终点 done', '停了：handover 接手，可改钉包', '历史留痕，仅执行当前 SPEC', '遵守 DAG / 写锁 / 累计预算'], 'gray')
    d.box(1210,1530,330,280,'收尾 ≠ 全部通过',[
        'Green：真实复测与 DoD 完成', '仅缺自动化环境：Yellow 收尾', '排队、锁等待、worker 退出', '均不能独立算作 MO 收尾', 'host-idle / planning-overdue', '有 ready 动作继续推进', '一个失败不提前拉起 Auditor'], 'orange')
    d.text(1375,1935,'细节阅读',24,weight=650)
    d.text(1375,1985,'02 · 子 MO 执行与反馈调整',21,'#4b5563')
    d.text(1375,2025,'03 · Auditor 跨模块收尾',21,'#4b5563')
    d.text(1375,2065,'04 · 二方库语义与复用',21,'#4b5563')
    d.legend(2270)
    d.save()


def module_execution():
    d=Diagram('module-execution',2470,'02','子 MO · 执行与反馈调整','SDD 先规划后执行、边执行边调整；TDD 从全量用例建立覆盖，再以路径证据修正实现')
    d.box(550,190,500,130,'子 MO · TASK 划分',[
        '继承 GO / 父 MO 的 scope / 全量 CASE',
        '职责、排除、允许写范围和依赖',
        '叶子 = 子业务流，自带四维与 SPEC'],controller=True)
    d.arrow([(800,320),(800,400)])
    d.box(550,400,500,185,'四维 → SPEC / 测试路径',[
        'UI → Logic → Adhesive → Resource',
        'Spec-Designer：实施规范 + CASE / PATH / ASSERT',
        '先按 capture_due 捕获、media_due 引用用户媒体',
        '骨架预填场景与测试源；PATH 准备方式 Ledger 补',
        '首版限时 45 分钟；可后补项记 debt'])
    d.arrow([(800,585),(800,610)])
    d.box(550,610,500,185,'MO 审核冻结',[
        '门禁全过且无人提问：Ledger 记评审即冻结',
        '测试源须能失败：拒恒真断言 / 表达式体 @Test',
        '欠项在静态审查前由 Ledger 开 CR 补齐，代码保留',
        '真实未决 / 需求验收授权变化交 Human'],controller=True)
    d.arrow([(800,795),(800,810)])
    d.box(550,810,500,130,'Implementer · 按 TASK 执行',[
        'Ledger 代写预检；同构建单元的叶子并行写',
        '任务先单测：自查红→绿两份记录为 red 证据',
        '冻结测试原样交付（可在写范围外）；编译通过即机械接受'])
    d.arrow([(800,940),(800,1010)])
    d.box(550,1010,500,180,'Test-Runner · 正式验证',[
        'build → unit 一派发（无人写入时），advance 代跑',
        'static 随模型跑的 automation 同派，非绿即停',
        '有适配器 static 单派；等调用方时 automation 先跑',
        '只回退出码与报错定位；结果已定即机械验收'])
    d.arrow([(800,1190),(800,1245)])
    d.diamond(800,1310,310,130,'验证结果','Green / Red / Yellow')
    d.arrow([(645,1310),(500,1310)],'green');d.label(570,1290,'Green','green')
    d.box(70,1220,430,180,'MO · DoD / 模块完成',[
        '全部必需路径有效 Green',
        'TASK 追溯 / checklist 完整',
        '已知债务登 debt issue，审计预列',
        '守卫通过即机械完成，不提前 Auditor'], 'green',True)
    d.arrow([(70,1310),(50,1310),(50,2180),(300,2180),(300,2240)],'green')
    d.arrow([(955,1310),(1110,1310)],'orange');d.label(1030,1290,'非 Green','orange')
    d.box(1110,1220,410,180,'现有诊断 → MO 分流',[
        '报错或断言失败：Ledger 诊断，派 Fixer',
        '其余 Diagnostician 只读，日志按需 grep',
        '环境 / 目标基线缺陷 → 审计延期',
        '不增加前置规划轮次'], 'orange',True)
    # One classified diagnosis feeds three distinct control branches.
    d.arrow([(1315,1400),(1315,1430),(285,1430)],'purple',end=False)
    for cx in (285,800,1315):
        d.arrow([(cx,1430),(cx,1480)],'purple')
    d.box(70,1480,430,180,'实现错误 → Fixer',[
        '当前 SPEC 已明确，实现与其不符',
        '预算内最小补丁 / 自验证 / fix_note',
        '不改冻结 TASK / 需求 / 验收',
        'MO 接受后重新正式测试'], 'purple')
    d.arrow('M70,1570 L60,1570 Q50,1555 40,1570 L35,1570 L35,1090 L550,1090','purple')
    d.label(285,1070,'新 build / unit / static + 正式复测','purple',18)
    d.box(550,1480,500,180,'规划缺口 → CR',[
        'scope 内功能 / 契约 / fidelity 遗漏、测试源缺陷',
        '诊断确认即开 CR；只新增 TASK / PATH 由 Ledger 审',
        'Implementer 更新已经 coding 的代码',
        '改已冻结内容 MO 审；语义 / 授权变化交 Human'], 'purple')
    # Jump over the diagnosis input: crossing is not a shared control junction.
    d.arrow('M1050,1570 L1080,1570 L1080,1440 Q1095,1430 1080,1420 L1080,1320 Q1095,1310 1080,1300 L1080,675 L1050,675','purple')
    d.box(1110,1480,410,180,'范围不足 → 父 MO / GO',[
        'realloc-request 上溯负责上游',
        '只改提出叶子且不挪用例：Ledger 接受重切',
        '重新冻结，更新代码并正式复测',
        '无关 MO 保留当前有效状态'], 'purple')
    d.arrow([(1520,1570),(1570,1570),(1570,350),(1080,350),(1080,255),(1050,255)],'purple')
    d.box(550,1750,500,260,'CR 重验范围',[
        '默认：全模块重验',
        '可选 MO TASK 独立性证明，绑定旧冻/新计划',
        '核对写范围、读依赖、共享 PATH 与追溯',
        '独立才保留未影响 TASK / 有效 Green',
        '新 build/unit/static；影响及非 Green 路径复测',
        '共享影响 / 无证明回退全验；过期漏报拒收'], 'orange')
    d.box(70,1750,430,230,'证据与路径统计',[
        '保留原 receipt / test_run_id / 执行基线',
        'Ledger 另记 validation_reuse 有效性',
        '宿主 / 模块 / TASK 统计；TASK 缺口按模块计',
        '复用成功单列，不计本次新执行',
        'Red / Yellow 不凭证明转 Green'], 'gray')
    d.box(1110,1750,410,230,'阻塞与明确收尾',[
        '已有提供方暂不可用：等待 / 恢复',
        '仅自动化环境缺失：Yellow / 未执行',
        '不耗 Fixer 轮次，不掩盖实际失败',
        '受阻 / 预算耗尽：留证明确挂起',
        '条件恢复后真实测试，不直接 Green'], 'orange')
    d.arrow([(1520,1310),(1550,1310),(1550,1865),(1520,1865)],'orange',dashed=True)
    d.arrow([(1315,1980),(1315,2180),(1300,2180),(1300,2240)],'orange')
    d.box(300,2240,1000,130,'本模块收尾 → 父汇总 → 全量门禁 → 统一宿主 Auditor',[
        '各 MO 独立完成 / 明确挂起；全 registry 收尾、无 worker / 可推进动作才统一审计',
        '审阅全部模块与宿主目标；局部独立性证明不免除 Auditor 权限'])
    d.box(70,190,430,160,'一任务 · 一 Run',[
        '执行唯一当前冻结 SPEC',
        'run 固定包版本；修订只留 history',
        '失败与预算保留；已验证修复随卡给兄弟叶子'], 'gray')
    d.box(70,420,430,160,'OpenSpec 六件套',[
        'proposal / spec / design',
        'tasks / status / checklist',
        'status / checklist 由 Ledger 投影',
        '骨架起稿；产物不限体量'], 'gray')
    d.box(70,760,430,210,'资源与 fidelity 输入',[
        'API / URL / image / icon 来源追溯',
        '清单由 Ledger 派生，派发时代拷，验收核对引用',
        'XML / 图层 / 代码取值按参数表复用',
        '存量捕获（设备 / 浏览器 / 导航器）或用户截图',
        '真实证据验证，不以 build 替代'], 'gray')
    d.box(1110,190,410,130,'冻结与执行门禁',[
        'SPEC 未冻结不生成代码',
        '代码未接受不派正式测试；自查无结果',
        '预检 / 锁 / 依赖 / 预算按步骤检查'], 'orange')
    d.box(1110,420,410,230,'SDD / TDD 控制原则',[
        '按明确规划先执行，再按反馈调整',
        '拿不准的库写成 spike 任务，不在规划期试建',
        '冻结前分配全量 CASE 与预期',
        'automation 逐路径收集错误证据',
        'Fixer 自测不能代替正式验证',
        '红→绿由作者自查留证，按任务计数'], 'gray')
    d.legend(2420)
    d.save()


def auditor_closure():
    d=Diagram('auditor-closure',2110,'03','统一 Auditor · 宿主审计与跨模块处理','独立 Auditor 保留审计验收权；修复由负责模块的 MO 派发 Fixer，正式 Testing 必须复核')
    d.box(340,195,920,115,'入口：GO 全量收尾门禁已满足',[
        '全部子 MO 本轮结束 + 所有父汇总有效 + 无活动 worker / 可推进动作',
        '审阅全部模块（含 Green）及宿主目标；波次集成已跑的 global path 只在 owner 代码变动时重跑'], 'orange')
    d.arrow([(800,310),(800,370)])
    d.box(500,370,600,135,'整体代码审查 → 分批收集',[
        'audit-code-review（骨架起笔，预列 debt）：目标/改动/冗余/复用','audit-collect（机械）：先治理 CR-*，再剩余 Red / Yellow','绑定 SPEC / PATH 证据；测试映射与 git 改动 Ledger 填'])
    d.arrow([(800,505),(800,565)])
    d.box(500,565,600,135,'根因分析 → 路由审核',[
        '治理用 fix / human；遗留可 fix / verify / human','finding 自带路由 / 根因已确认：Ledger 路由并代审','trace：叶子即开 CR（根因已确认则机械），代码保留'],controller=True)
    d.box(90,370,330,200,'复用与公共能力治理',[
        '重复实现 / 接线 / 公共能力',
        '核对已选映射与影响消费者',
        '外部源码默认只读',
        '无修改授权 → human 路由'], 'orange')
    d.arrow([(500,630),(300,630),(300,820)])
    d.label(300,760,'fix','blue')
    d.arrow([(800,700),(800,820)])
    d.label(800,764,'verify','blue')
    d.arrow([(1100,630),(1310,630),(1310,1080)],'orange')
    d.label(1310,770,'human','orange')
    d.box(90,820,420,145,'MO 派发 → Fixer 预检',[
        'audit-work 由 Ledger 接受，派发批准的一轮','遵守冻结契约 / 写范围 / 总预算','补丁、回归证据与修复 memory'], 'purple')
    d.box(590,820,420,145,'验证路径',[
        '前置条件已恢复 / 无需补丁','仍须新 Main 结果','不能沿用旧非 Green 直接通过'])
    d.arrow([(300,965),(300,1155),(590,1155)],'purple')
    d.arrow([(800,965),(800,1080)])
    d.box(590,1080,420,155,'构建 / 单测 / 静态 → 路径回归',[
        '按 finding 依赖图交错推进','验证 owner / source / 中间与下游','审计影响模块完整回归；无关 Green 保留','发现模块与负责模块相同时合并证据'])
    d.arrow([(1010,1155),(1120,1155)],'orange')
    d.label(1067,1136,'失败','orange')
    d.box(1120,1080,380,155,'记录人工问题',[
        '不可控 / 复核失败 / 证据受阻','保留 SPEC / 路径 / 根因','只挂起相关分支与依赖下游','其他无冲突分支继续'], 'orange')
    d.arrow([(800,1235),(800,1295)],end=False)
    d.arrow([(1310,1235),(1310,1295),(800,1295)],'orange',end=False)
    d.arrow([(800,1295),(800,1360)])
    d.label(800,1330,'剩余可执行分支已结束','gray')
    d.box(500,1360,600,145,'Auditor · 核对当前证据 → 裁决',[
        'audit-verdict：统一审阅 owner / source 新证据','复测全绿且无待人工：Ledger 代 Auditor 裁决','Fixer 自测不能代替 Testing 与独立审计'],controller=True)
    d.arrow([(640,1505),(640,1540),(400,1540),(400,1590)])
    d.label(430,1540,'已解决 / 仅自动化缺测','green')
    d.arrow([(960,1505),(960,1540),(1200,1540),(1200,1590)],'orange')
    d.label(1190,1540,'Red / 其他 Yellow','orange')
    d.box(90,1590,620,145,'批次收尾 → 刷新父汇总',[
        '修复导致父汇总失效时重新核验并提交','保留 Green 或自动化未验证清单；不空等','只重审修复改动的模块，再收集剩余问题'], 'green')
    d.box(890,1590,620,145,'根因报告 → 等待人工审核',[
        'awaiting-human：保留各次断言、证据与问题归属','审核决定绑定当前报告摘要；不自动追加修复'], 'orange')
    d.arrow([(400,1735),(400,1795)])
    d.box(90,1795,620,155,'独立审阅收尾 → 全局报告',[
        '复测由 Ledger 派发并代预检；空清单只审阅','全通过 → 全局 Green → 按授权交付','仅缺自动化环境 → Yellow / 未执行报告收尾'], 'green')
    d.arrow([(1200,1735),(1200,1795)],'purple')
    d.box(890,1795,620,155,'人工批准 → GO 释放批次 → 受控恢复',[
        'audit-release 后按原因 resume / recover / CR','需要时重新 plan / freeze；恢复不会直接 Green','再次满足全量收尾门禁，才可创建新审计批次'], 'purple')
    d.text(800,2015,'先整体审查代码，再治理与复核；测试覆盖遗留及全部受影响用例，Auditor 与 Fixer 始终分离。',22,'#4b5563')
    d.legend(2060)
    d.save()


def reuse_flow():
    d=Diagram('reuse-dependencies',2270,'04','二方库 · 从功能语义到真实复用','复用能力辅助需求实现；业务要求控制验收，已有库的行为不能替代用户需求')
    d.box(70,205,700,135,'TARGET · 目标项目已有能力',[
        '业务模块 / 公共服务 / 已接入二方库及封装',
        '目标画像逐功能记无 / 壳 / 部分 / 已有；优先复用生产实现，避免重复迁移'])
    d.box(830,205,700,135,'用户指定 · 其他项目模块',[
        'reuse_sources：root / module_paths / 用途',
        '配置保存 → prepare 固化；源码只读，接入方式另行核验'])
    for x in (420,1180): d.arrow([(x,340),(x,395),(800,395)],end=False)
    d.arrow([(800,395),(800,450)])
    d.box(400,450,800,160,'GO · 语义抽取与初始需求对齐',[
        '业务意图 / 输入输出 / 前置与状态 / 副作用 / 异常',
        '公开 API / 版本 / 平台架构 / 传递依赖 / 生产调用链',
        'reuse-catalog.json + 源码/API 证据与摘要 + 需求缺口'],controller=True)
    d.arrow([(800,610),(800,680)])
    d.box(400,680,800,140,'父 MO · 模块需求映射与统一分工',[
        '筛选适用能力，核对语义差异，统一共享适配 owner',
        '分配子 scope + 复用上下文；记录提供方 / 消费方依赖'],controller=True)
    d.arrow([(800,820),(800,880)])
    d.box(400,880,800,125,'子 MO / Spec Designer · 逐需求决策',[
        'requirement → capability / decision → task → PATH',
        '接线 / 差异 / 版本进 reuse-plan；API 与数据契约对齐取数 / 计算'])
    d.arrow([(800,1005),(800,1060)],end=False)
    d.arrow([(225,1060),(1365,1060)],end=False)
    for x,title,body in [
        (60,'reuse · 直接使用',['语义和架构兼容','真实接入现有能力']),
        (440,'adapt · 适配使用',['明确输入/状态等差异','补适配 tasks 与回归']),
        (820,'reference · 仅参考',['提取可用的业务语义','在目标架构内实现']),
        (1200,'new · 自行实现',['记录无匹配/拒绝理由','实现需求剩余缺口'])]:
        d.arrow([(x+165,1060),(x+165,1120)])
        d.box(x,1120,330,125,title,body)
        d.arrow([(x+165,1245),(x+165,1305)],end=False)
    d.arrow([(225,1305),(1365,1305)],end=False)
    d.arrow([(800,1305),(800,1365)])
    d.box(400,1365,800,130,'Plan 澄清 → 复用决策与 SPEC 一并冻结',[
        '接入位置 / 版本 / 传递依赖 / 可行性证据齐备；未决问题先解决',
        'stage-plan.reuse_plan_ref → reuse-plan.json → reuse-catalog.json',
        '用户需求控制验收；冻结 checklist 通过后才允许 Coding'])
    d.arrow([(800,1495),(800,1555)])
    d.box(400,1555,800,140,'Implementer / Fixer · 上下文预检后按冻结映射 Coding',[
        '实际依赖 / 解析版本 / 初始化与 DI / 生产入口 / 差异适配',
        'Task Trace + reuse_trace + 真实提供方绑定证据',
        '换库或改行为需 CR；引用外部来源不授予修改权限'])
    d.arrow([(800,1695),(800,1765)])
    d.box(400,1765,800,140,'代码接受 → 构建 → 自动化与保真验证',[
        '正常 / 边界 / 异常 / 取消；真实提供方接线与适配差异',
        '编译、导入或 mock 通过，不能代替必要的集成验证',
        '实现错误 → Fixer；契约缺口 → CR；超 scope → 父 MO / GO'])
    d.arrow([(800,1905),(800,1970)])
    d.box(400,1970,800,145,'全量收尾后 → Auditor 跨模块验证',[
        '定位 source / capability / mapping / version 与影响消费者',
        '按依赖图修复和正式复测；失败保留根因待人工',
        '全部必需路径与最终全局审计通过，才记录 Green'], 'green')
    d.box(60,690,290,255,'重要边界',[
        'API 同名不等于语义等价',
        '候选不等于运行依赖',
        'reference 不宣称已接库',
        '复用不缩减验收范围',
        '外部来源默认只读',
        '未决业务边界交人工'], 'orange')
    d.box(60,440,290,210,'来源评审门禁',[
        '声明来源不可用 → 阻塞',
        '不能当作无候选直接 new',
        '已评审且无匹配才选 new',
        '保留搜索与拒绝理由',
        '未决问题禁止冻结'], 'orange')
    d.box(1250,690,290,255,'接入可行性',[
        'existing-target / package',
        'source-module',
        'reference-only',
        '可读源码不等于可接入',
        '核实定位 / 版本 / 平台',
        '证据绑定路径与 sha256',
        '稳定库不虚设待完成 MO'], 'gray')
    d.box(1250,1535,290,195,'选中提供方证据变化',[
        '相关计划 / 旧测试失效',
        '按影响核验 TASK 独立性',
        'CR / 上溯 → 冻结 → 正式复测',
        '无关模块继续'], 'purple')
    d.arrow([(1540,1630),(1560,1630),(1560,1030),(1230,1030),(1230,945),(1200,945)],'purple',dashed=True)
    d.text(800,2180,'来源、目录、映射和绑定证据均经 Ledger；语义分析由 Agent 完成，结构校验不能证明行为等价。',21,'#4b5563')
    d.legend(2220)
    d.save()


if __name__ == '__main__':
    overview()
    module_execution()
    auditor_closure()
    reuse_flow()
