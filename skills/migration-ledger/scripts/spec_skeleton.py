"""Skeletons of a leaf's OpenSpec documents, written from the allocation the Ledger accepted.

A Spec-Designer starts from the leaf's four-dimension specification, not from an empty template: scope, requirements,
cases and every allocated item with its source, target and acceptance are in place, and each part only its author can
write is marked. A plan whose definitions still hold a mark is refused, so a skeleton is never frozen as a specification.

  spec_skeleton.py --root <run_root> --module <id> --out <absolute directory in the role's staging>
"""
import argparse
import json
import sys
from pathlib import Path

from contracts import SKELETON_MARK, Rejected, file_ref, require


def todo(what):
    return f'{SKELETON_MARK}：{what}]]'


def documents(s, m):
    """{file name: text} for one leaf: proposal, spec, design and tasks."""
    import dimensions
    mid = m['module_id']
    analysis, items = dimensions.load(m['dimension_analysis_ref'], mid)
    scope = m.get('scope') or {}
    requirements = list(scope.get('requirement_ids') or sorted({rid for item in items.values() for rid in item['requirement_ids']}))
    listed = lambda values: ''.join(f'- {value}\n' for value in values) or '- none\n'
    ids = lambda rows: '、'.join(f'`{iid}`' for iid in rows) or '—'
    ref = lambda value: f"{value['path']} · sha256={value['sha256']}" if isinstance(value, dict) and value.get('path') else '—'
    proposal = (f"# {mid} {(scope.get('in') or [mid])[0]}\n\n## Why\n{todo('业务目标、迁移原因、可观察收益')}\n\n"
                f"## What Changes\n{listed(scope.get('in') or [])}\n不在范围：\n{listed(scope.get('out') or [])}\n"
                f"## Capabilities\n{todo('新增或修改的 capability；没有则写 none')}\n\n"
                f"## Impact\n{todo('旧架构到新架构的影响、上下游契约、数据迁移、安全与性能约束')}\n\n"
                f"## References\n- run_id: {s.get('run_id')}\n- module_id: {mid}\n- global_spec_ref: {ref(s.get('global_spec'))}\n"
                f"- dimension_analysis_ref: {ref(m['dimension_analysis_ref'])}\n- cases: {'、'.join(m.get('case_ids', []))}\n")
    mapping = ''.join(f"| {item['source_locator']} | {item['behavior']} | {item['target_binding']} | {item['target_strategy']} | "
                      f"{'、'.join(item['requirement_ids'])} | `{iid}` |\n" for iid, item in items.items())
    dimensions_text = ''
    for row in analysis.get('dimensions', []):
        dimensions_text += f"### {row['dimension']}（{row.get('status')}：{row.get('reason', '')}）\n"
        for item in row.get('items') or [] if row.get('status') == 'applicable' else []:
            dimensions_text += (f"- `{item['item_id']}`：{item['behavior']}；验收：{item['acceptance']}；CASE：{'、'.join(item['case_ids'])}\n"
                                f"  - {todo('实现要点与接线')}\n")
        dimensions_text += '\n'
    design = (f"# {mid} Design\n\n## Context\n{todo('全局规范、架构、legacy 基线与相关模块接口')}\n\n"
              f"## Goals / Non-Goals\n范围内：\n{listed(scope.get('in') or [])}\n范围外：\n{listed(scope.get('out') or [])}\n"
              "## Legacy → Target Mapping\n| Legacy 路径/符号 | 行为 | Target 绑定 | 策略 | REQ-ID | Item |\n| --- | --- | --- | --- | --- | --- |\n"
              f"{mapping}\n## UI → Logic → Adhesive → Resource\n{dimensions_text}"
              f"## Decisions\n{todo('候选方案、选择及理由')}\n\n## Test Design\n{todo('正常、边界、异常路径与允许 Mock 的外部边界')}\n\n"
              f"## Risks / Rollback\n{todo('风险、回滚条件与操作')}\n")
    spec, number = '## ADDED Requirements\n', 0
    for rid in requirements:
        owned = {iid: item for iid, item in items.items() if rid in item['requirement_ids']}
        spec += (f"\n### Requirement: {todo('需求名称')}\nRequirement-ID: {rid}\n{rid}: The system SHALL {todo('可观察的行为及边界')}.\n"
                 f"Items: {ids(owned)}\n")
        for cid in sorted({cid for item in owned.values() for cid in item['case_ids']}) or ['']:
            number += 1
            spec += (f"\n#### Scenario: {todo('场景名称')}\nScenario-ID: SCN-{mid}-{number:03d}\n" + (f"CASE: {cid}\n" if cid else '') +
                     f"- **GIVEN** {todo('前置条件')}\n- **WHEN** {todo('触发行为')}\n- **THEN** {todo('可断言结果')}\n")
    tasks = (f"# {mid} Tasks\n\n## Implementation\n- [ ] TASK-{mid}-001 {todo('可执行任务名称；按需拆成多个 TASK')}\n"
             f"  - Requirements: {'、'.join(requirements)}\n  - Cases / Paths: {'、'.join(m.get('case_ids', []))} / {todo('PATH-ID')}\n"
             f"  - Items: {ids(items)}\n  - Write scope: {'、'.join(m.get('write_paths', []))}\n"
             f"  - Action: {todo('具体改动')}\n  - Done when: {todo('可核验结果')}\n\n"
             "## Traceability\n| REQ-ID | TASK-ID | CASE-ID | Item |\n| --- | --- | --- | --- |\n" +
             ''.join(f"| {rid} | TASK-{mid}-001 | {'、'.join(sorted({cid for item in items.values() if rid in item['requirement_ids'] for cid in item['case_ids']}))} | "
                     f"{ids({iid: item for iid, item in items.items() if rid in item['requirement_ids']})} |\n" for rid in requirements))
    return {'proposal.md': proposal, 'spec.md': spec, 'design.md': design, 'tasks.md': tasks}


def write(root, module_id, out):
    import ledger
    s, _ = ledger.read_events(root)
    m = (s or {}).get('modules', {}).get(module_id)
    require(m and m.get('dimension_analysis_ref') and not m.get('decomposition_required'),
            'skeletons are written for a leaf that has its four-dimension analysis')
    out = Path(out)
    require(out.is_absolute(), 'absolute output directory required')
    texts = documents(s, m)
    require(not any((out / name).exists() for name in texts), 'refusing to overwrite documents in ' + str(out))
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, text in texts.items():
        (out / name).write_text(text)
        files[name] = file_ref(out / name)
    return {'module_id': module_id, 'files': files, 'unfilled': sum(text.count(SKELETON_MARK) for text in texts.values()),
            'next_action': 'write every marked part; a plan whose definitions still hold a mark is refused'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', required=True); parser.add_argument('--module', required=True); parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(write(args.root, args.module, args.out), ensure_ascii=False, indent=2))
        return 0
    except (Rejected, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
