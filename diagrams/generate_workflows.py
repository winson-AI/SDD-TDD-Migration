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
    d=Diagram('workflow',2320,'01','三层编排 · 迁移总览','GO 拆模块 → 父 MO 拆子模块 → 子 MO 拆 tasks；独立执行，逐层收尾，统一审计')
    d.box(100,190,1020,140,'用户输入 → 项目上下文固化',[
        '规范 / 新架构 / 存量与目标代码 / 知识 / 测试用例 / 可选外部复用来源',
        '宿主 init / update 配置；prepare 固化本轮快照'], 'gray')
    d.arrow([(610,330),(610,425)])
    d.band(60,365,1100,230,'GO  ·  全局规划','全局管理迁移、DAG、锁与依赖')
    d.box(100,425,1020,165,'GO 上下文 / 功能清单 → 划模块 → 模块四维分析',[
        '默认从测试用例汇总抽取；无汇总则先理解存量源码；查漏，有疑问即人工',
        'TARGET + 指定二方库：reuse-catalog / 功能语义 / 行为差异 / 接入可行性',
        '先确定模块 scope，再按 UI → Logic → Adhesive → Resource 分析实现',
        'project：多个根模块；single-module：一个根模块，其子功能仍须拆分'],controller=True)
    # Fan out through a shared branch; two parents show project multiplicity.
    d.arrow([(610,590),(610,690)],end=False)
    d.arrow([(340,690),(880,690)],end=False)
    for x in (340,880): d.arrow([(x,690),(x,700)])
    d.band(60,635,1100,265,'父 MO  ·  认领与拆分','每个父 MO 持续看护自己认领的整个模块')
    d.box(100,700,480,170,'父 MO · 根模块 A',[
        '认领模块 / 实现 / 四维上下文', '先划子模块 A1 / A2 的 scope', '再逐子模块四维分析', '明确实现指导 / owner / 完整性'],controller=True)
    d.box(640,700,480,170,'父 MO · 其他根模块 × N',[
        'project 按根模块分别建立父 MO', '先划子模块范围，再逐个分析', '继承实现 / 复用 / 四维上下文', 'single-module 仅保留选定根模块'],controller=True)
    # Anchor branch endpoints to the cards (container crossings remain open).
    for x in (340,880):
        d.arrow([(x,870),(x,940),(610,940)],end=False)
    d.arrow([(610,940),(610,980)])
    d.box(100,980,1020,110,'GO 审核拆分 → 登记子模块 → 全局覆盖验收',[
        '核验父子四维覆盖 / N/A 依据 / CASE / 复用 owner / DAG；派发独立子 MO'])
    d.arrow([(610,1090),(610,1220)],end=False)
    d.arrow([(215,1220),(1010,1220)],end=False)
    d.band(60,1170,1100,265,'子 MO  ·  任务规划与独立执行','单个失败不取消或污染无关子模块')
    for x,title,subtitle in [(100,'子 MO · A1','子 scope A1'),(365,'子 MO · A2','子 scope A2'),(630,'子 MO · B1','子 scope B1'),(895,'子 MO · B…','其他子 scope')]:
        cx=x+115
        d.arrow([(cx,1220),(cx,1240)])
        d.box(x,1240,230,165,title,['先划任务 scope','四维分析 → 冻结','编码→构建→自动化','修复 / DoD / 挂起'],controller=True)
    for centers,summaryx in [((215,480),100),((745,1010),640)]:
        for cx in centers: d.arrow([(cx,1405),(cx,1480)],end=False)
        d.arrow([(centers[0],1480),(centers[1],1480)],end=False)
        d.arrow([(sum(centers)/2,1480),(sum(centers)/2,1520)])
        d.box(summaryx,1520,480,115,'对应父 MO 汇总',[
            '等全部孩子本轮结束，检查完整性','module-summary 绑定当前子版本'])
    for x in (340,880): d.arrow([(x,1635),(x,1670),(610,1670)],end=False)
    d.arrow([(610,1670),(610,1710)],'orange')
    d.box(100,1710,1020,140,'GO · 全量收尾门禁',[
        '所有子 MO：DoD 完成 / 自动化缺测已记录 / 其他问题明确挂起',
        '所有父汇总有效；无活动 worker，也无可推进 / 恢复动作'], 'orange',True)
    d.arrow([(610,1850),(610,1910)])
    d.box(100,1910,1020,110,'统一 Auditor · 问题收尾',[
        '有遗留：收集 Red / Yellow → 根因 → Fixer → Testing → 裁决（详图 03）',
        '纯自动化缺环境：保留未验证清单，其他可执行任务继续'])
    d.arrow([(610,2020),(610,2080)])
    d.box(100,2080,1020,125,'独立审阅收尾 → 全局报告',[
        '固定基线，只复核遗留 / 受影响路径；无遗留只审阅，不全量重跑',
        '全通过才 Green；仅缺自动化环境：Yellow / 未执行报告，本轮可结束'], 'green')
    # Shared planes: explanatory cards, deliberately not direct agent channels.
    d.box(1210,190,330,280,'全局读取视野',[
        'GO / 父 MO / 子 MO', '均可读全局存量与目标代码', '架构 / 知识 / 分工 / 复用来源', '', '局部 context pack 聚焦任务', '不截断全局只读上下文'], 'gray')
    d.box(1210,540,330,270,'范围逐层细化',[
        'GO → 根模块 scope', '父 MO → 子模块 scope', '子 MO → tasks', '', '范围先定，四维分析指导实现', '跨模块或不确定处交人工'], 'orange')
    d.box(1210,880,330,280,'Ledger · 唯一总线',[
        '分配包 / 事件 / 状态 / 证据', 'planning_context：全局视野', 'module_inputs：认领范围', 'context-submit：预检留证', '原节点接受后才允许推进', '父聚合颜色不回写子模块'], 'green')
    d.box(1210,1230,330,230,'宿主执行层',[
        '实际启动 / 恢复 subagent', '绑定实例、模块及 Used Skills', '遵守 DAG / 写锁 / 预算', '', '状态投影不代表 Agent 已启动'], 'gray')
    d.box(1210,1530,330,280,'收尾 ≠ 全部通过',[
        'Green：真实复测与 DoD 完成', '仅缺自动化环境：Yellow 收尾', '排队、锁等待、worker 退出', '均不能独立算作 MO 收尾', '', '有 ready 动作继续推进', '一个失败不提前拉起 Auditor'], 'orange')
    d.text(1375,1935,'细节阅读',24,weight=650)
    d.text(1375,1985,'02 · 子 MO 执行与修复',21,'#4b5563')
    d.text(1375,2025,'03 · Auditor 跨模块收尾',21,'#4b5563')
    d.text(1375,2065,'04 · 二方库语义与复用',21,'#4b5563')
    d.legend(2270)
    d.save()


def module_execution():
    d=Diagram('module-execution',1970,'02','子 MO · 执行与首轮修复','每个子 MO 独立维护 SPEC、tasks、测试结果、修复预算和 DoD；父 MO 持续看护并等待')
    d.box(560,190,480,130,'认领上下文 → 划定任务 scope',[
        '子模块实现 / 四维分析 / 全局上下文','划任务：职责 / 排除 / 允许写范围','禁止再次创建下一层 MO'],controller=True)
    d.arrow([(800,320),(800,380)])
    d.box(560,380,480,140,'任务四维分析 → SPEC / 测试设计',[
        'UI → Logic → Adhesive → Resource','绑定任务 scope，明确具体实现指导','OpenSpec / PATH / ASSERT；N/A 留证'])
    d.arrow([(800,520),(800,580)])
    d.box(560,580,480,105,'Plan 澄清 → 冻结',[
        'Human 决策 + 四维覆盖 checklist','子 MO 接受当前版本冻结'])
    d.arrow([(800,685),(800,745)])
    d.box(560,745,480,125,'Coding 预检 → 实现 → MO 接受',[
        '按任务 scope + 四维指导实现','提交四维证据 / 资源及真实消费者','依赖满足 / 写锁 / 全局覆盖 / 预算'])
    d.arrow([(800,870),(800,920)])
    d.box(560,920,480,150,'Test-Runner · 构建 → 自动化',[
        'build Green 后预检自动化环境','可用：Main 按用例路径验证','缺环境：Yellow / 未执行（旁路）'])
    d.arrow([(800,1070),(800,1105)])
    d.diamond(800,1170,310,130,'三态结果','Green / Red / Yellow')
    d.arrow([(645,1170),(500,1170)],'orange');d.label(570,1152,'Green','green')
    d.box(70,1100,430,150,'子 MO · DoD 验收',[
        '全部必需路径有效 Green','任务追溯完整，无遗留 Red / Yellow','不通过则补齐合法动作或明确挂起'], 'green')
    d.arrow([(285,1250),(285,1500)])
    d.label(285,1380,'DoD 满足','green')
    d.box(70,1500,430,130,'模块完成 → Ledger',[
        '子 MO 为模块阶段唯一验收 owner','记录结果、版本与修复 memory'], 'green')
    d.arrow([(955,1170),(1110,1170)],'orange');d.label(1030,1148,'其他非 Green','orange')
    d.box(1110,1100,410,140,'Diagnostician · 根因',[
        '只读分析；Red / Yellow 留根因','子 MO 接受当前版本诊断', '确认依赖 / 外围问题直接留待审计'], 'orange')
    d.arrow([(1315,1240),(1315,1315)],'orange')
    d.diamond(1315,1380,300,130,'可修复且首轮可用？')
    d.arrow([(1465,1380),(1555,1380),(1555,767),(1520,767)],'purple')
    d.label(1510,1350,'是','purple')
    d.box(1110,700,410,135,'Fixer 预检 → 自动一轮',[
        '最小补丁 + 自验证 + fix_note','子 MO 接受补丁，旧结果失效','修复记录保留为 memory'], 'purple')
    d.arrow([(1110,767),(1080,767),(1080,990),(1040,990)],'purple')
    d.label(1305,882,'重新构建，再正式自动化复测','purple')
    d.arrow([(1315,1445),(1315,1540)],'orange');d.label(1315,1495,'否 / 一轮仍未通过','orange')
    d.box(1110,1540,410,130,'留证 → 明确挂起',[
        'audit-defer / 依赖 / 人工阻塞','保留根因、路径、结果与恢复点','无关兄弟继续推进'], 'orange')
    d.arrow([(285,1630),(285,1720),(600,1720),(600,1770)])
    d.arrow([(1315,1670),(1315,1720),(1000,1720),(1000,1770)],'orange')
    d.arrow([(800,1235),(800,1365)],'orange')
    d.label(800,1305,'仅自动化环境缺失','orange')
    d.box(560,1365,480,180,'Yellow 缺测 → 本轮收尾',[
        '当前 build Green；自动用例未执行','记录 automation-deferred','可执行的下游 / 并行任务继续','不是 DoD 或功能验收通过'], 'orange')
    d.arrow([(800,1545),(800,1770)],'orange')
    d.box(400,1770,800,115,'本子 MO 收尾 → 父 MO 检查与汇总',[
        '当前子 MO 已收尾不触发提前审计；仍等待其他子 MO 和其他父模块'])
    d.box(1110,190,410,190,'编码前阻塞',[
        '缺输入 / 未决边界 / 目标不可行',
        'context-submit 留证 → 原节点验收',
        '先澄清、恢复条件或明确挂起',
        'SPEC 未冻结不编码',
        '代码未接受不启动 Main'], 'orange')
    d.box(70,190,400,150,'认领范围',[
        'assigned_module 绑定分配包','需求 / CASE / 写范围不得越界','全局可读不扩大执行权限'], 'gray')
    d.box(70,410,400,150,'OpenSpec 六件套',[
        'proposal / spec / design','tasks / status / checklist','测试设计在冻结前，执行在代码后'], 'gray')
    d.box(70,700,400,210,'契约变化 → CR',[
        'Fixer 只能提出变更建议','Spec Designer 分析；子 MO 审核','业务语义 / 不确定边界交人工','修订后重新冻结，再实现与测试','任何反馈都不能直接写 Green'], 'purple')
    d.box(1110,440,410,190,'选中提供方 / 接入证据变化',[
        '相关计划与旧测试证据失效',
        '影响分析 → CR / 重规划 → 冻结',
        '新代码接受后正式复测',
        '仅影响相关消费者，无关 MO 继续'], 'purple')
    d.legend(1920)
    d.save()


def auditor_closure():
    d=Diagram('auditor-closure',2110,'03','Auditor · 跨模块处理与最终裁决','独立 Auditor 保留审计验收权；修复由负责模块的 MO 派发 Fixer，正式 Testing 必须复核')
    d.box(340,195,920,115,'入口：GO 全量收尾门禁已满足',[
        '全部子 MO 本轮结束 + 所有父汇总有效 + 无活动 worker / 可推进动作',
        '本图展开遗留处理；global_paths 可为空；无遗留只独立审阅'], 'orange')
    d.arrow([(800,310),(800,370)])
    d.box(500,370,600,135,'收集遗留 → Auditor 上下文预检',[
        'audit-collect：Red / Yellow / blocked → finding','读取发现模块与负责模块的 SPEC / tasks','绑定 PATH、复用映射、提供方版本及测试证据'])
    d.arrow([(800,505),(800,565)])
    d.box(500,565,600,135,'根因分析 → 路由审核',[
        'Auditor 给出 fix / verify / human 方案','GO 审核提供方 owner、消费者及依赖图','无有效冻结 SPEC / 代码：转人工恢复规划'],controller=True)
    d.box(90,370,330,200,'二方库问题归属',[
        '提供方缺陷 / 不可用 / 版本漂移',
        '核对已选映射与影响消费者',
        '外部源码默认只读',
        '无修改授权 → human 路由'], 'orange')
    d.arrow([(500,630),(300,630),(300,820)])
    d.label(300,760,'fix','blue')
    d.arrow([(800,700),(800,820)])
    d.label(800,764,'verify','blue')
    d.arrow([(1100,630),(1310,630),(1310,1080)],'orange')
    d.label(1310,770,'human','orange')
    d.box(90,820,420,145,'Fixer 预检 → MO 派发',[
        '接受 audit-work，派发批准的一轮','遵守冻结契约 / 写范围 / 总预算','补丁、回归证据与修复 memory'], 'purple')
    d.box(590,820,420,145,'验证路径',[
        '前置条件已恢复 / 无需补丁','仍须新 Main 结果','不能沿用旧非 Green 直接通过'])
    d.arrow([(300,965),(300,1155),(590,1155)],'purple')
    d.arrow([(800,965),(800,1080)])
    d.box(590,1080,420,155,'构建 → 自动化 → 记录结果',[
        '按 finding 依赖图交错推进','验证 owner / source / 中间与下游','原 Green 受影响也须正式复测','发现模块与负责模块相同时合并证据'])
    d.arrow([(1010,1155),(1120,1155)],'orange')
    d.label(1067,1136,'失败','orange')
    d.box(1120,1080,380,155,'记录人工问题',[
        '不可控 / 复核失败 / 证据受阻','保留 SPEC / 路径 / 根因','只挂起相关分支与依赖下游','其他无冲突分支继续'], 'orange')
    d.arrow([(800,1235),(800,1295)],end=False)
    d.arrow([(1310,1235),(1310,1295),(800,1295)],'orange',end=False)
    d.arrow([(800,1295),(800,1360)])
    d.label(800,1330,'剩余可执行分支已结束','gray')
    d.box(500,1360,600,145,'Auditor · 核对当前证据 → 裁决',[
        'audit-verdict：统一审阅 owner / source 新证据','已解决 / 缺测未验证 / 人工问题分别记录','Fixer 自测不能代替 Testing 与独立审计'],controller=True)
    d.arrow([(640,1505),(640,1540),(400,1540),(400,1590)])
    d.label(430,1540,'通过 / 仅自动化缺测','green')
    d.arrow([(960,1505),(960,1540),(1200,1540),(1200,1590)],'orange')
    d.label(1190,1540,'Red / 其他 Yellow','orange')
    d.box(90,1590,620,145,'批次收尾 → 刷新父汇总',[
        '修复导致父汇总失效时重新核验并提交','保留 Green 或自动化未验证清单；不空等','完整跨模块验证后，修复 memory 才可复用'], 'green')
    d.box(890,1590,620,145,'根因报告 → 等待人工审核',[
        'awaiting-human：保留各次断言、证据与问题归属','审核决定绑定当前报告摘要；不自动追加修复'], 'orange')
    d.arrow([(400,1735),(400,1795)])
    d.box(90,1795,620,155,'独立审阅收尾 → 全局报告',[
        '遗留需 audit-testing；空清单只审阅证据','全通过 → 全局 Green → 按授权交付','仅缺自动化环境 → Yellow / 未执行报告收尾'], 'green')
    d.arrow([(1200,1735),(1200,1795)],'purple')
    d.box(890,1795,620,155,'人工批准 → GO 释放批次 → 受控恢复',[
        'audit-release 后按原因 resume / recover / CR','需要时重新 plan / freeze；恢复不会直接 Green','再次满足全量收尾门禁，才可创建新审计批次'], 'purple')
    d.text(800,2015,'遍历全部模块 ≠ 重跑全部用例；无遗留只独立审阅，Auditor 与 Fixer 始终分离。',22,'#4b5563')
    d.legend(2060)
    d.save()


def reuse_flow():
    d=Diagram('reuse-dependencies',2270,'04','二方库 · 从功能语义到真实复用','复用能力辅助需求实现；业务要求控制验收，已有库的行为不能替代用户需求')
    d.box(70,205,700,135,'TARGET · 目标项目已有能力',[
        '业务模块 / 公共服务 / 已接入二方库及封装',
        '自动纳入评估，优先检查生产实现，避免重复迁移'])
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
        '接线、差异、版本及验证进入 design/tasks 与 reuse-plan.json'])
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
        '本模块可修复先一轮 Fixer；提供方/外围问题留证待 Auditor'])
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
        '仅相关消费者回到规划',
        'CR → 冻结 → 正式复测',
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
