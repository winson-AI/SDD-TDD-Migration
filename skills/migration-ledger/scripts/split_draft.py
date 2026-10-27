"""A draft of a root's split, cut from its feature inventory, for the Module-Orchestrator to edit and submit.

The leaves are the nodes one level below what the root's features share; a node with too many cases splits one level
further, nodes that share a case are one leaf (a case has one holder), and nodes too small to stand alone join the
smallest other leaf until each holds LEAF_MIN_CASES. Every leaf names its nodes, cases, requirements and the features it
does; what only the orchestrator can write (dimension analysis, behaviour review, the screens it anchors on, narrower
write paths) is marked [[待写 and refused while left. A root with fewer cases than two leaves gets no split.

  split_draft.py --root <run_root> --module <id> --out <absolute directory in the role's staging>
"""
import argparse
import json
from pathlib import Path
import sys

from contracts import SKELETON_MARK, Rejected, check_ref, file_ref, keyed, read_json, require


def todo(what):
    return f'{SKELETON_MARK}：{what}]]'


def nodes(features, depth):
    """{node path: [feature ids]}: the features grouped by their functional_path cut at `depth` segments."""
    out = {}
    for fid, f in features.items():
        parts = [p for p in str(f.get('functional_path') or fid).split('/') if p]
        out.setdefault('/'.join(parts[:depth] or parts), []).append(fid)
    return out


def groups(features, cases, minimum, maximum):
    """[(node paths, feature ids)]: the leaves of the draft."""
    split = [str(f.get('functional_path') or fid).split('/') for fid, f in features.items()]
    shared = 0
    while all(len(p) > shared + 1 for p in split) and len({p[shared] for p in split}) == 1:
        shared += 1  # the depth every feature path shares
    pending, done = [(shared + 1, dict(features))], []
    while pending:
        depth, held = pending.pop()
        for node, fids in sorted(nodes(held, depth).items()):
            count = len({c for fid in fids for c in features[fid]['case_ids']} & cases)
            deeper = len(nodes({fid: held[fid] for fid in fids}, depth + 1)) > 1
            if count > maximum and deeper:
                pending.append((depth + 1, {fid: held[fid] for fid in fids}))
            else:
                done.append(([node], list(fids)))
    merged = True
    while merged:  # nodes that share a case are one leaf
        merged = False
        for i in range(len(done)):
            for j in range(i + 1, len(done)):
                if {c for fid in done[i][1] for c in features[fid]['case_ids']} & {c for fid in done[j][1] for c in features[fid]['case_ids']}:
                    done[i] = (done[i][0] + done[j][0], done[i][1] + done[j][1]); del done[j]; merged = True
                    break
            if merged:
                break
    size = lambda g: len({c for fid in g[1] for c in features[fid]['case_ids']} & cases)
    while len(done) > 1 and min(map(size, done)) < minimum:  # too small to stand alone: join the smallest other leaf
        done.sort(key=size)
        small, rest = done[0], done[1:]
        target = min(range(len(rest)), key=lambda k: size(rest[k]))
        rest[target] = (rest[target][0] + small[0], rest[target][1] + small[1])
        done = rest
    return done


def draft(s, mid):
    import decomposition
    parent = s['modules'].get(mid)
    require(parent and parent.get('decomposition_required'), 'a split is drafted for a root that waits for one')
    cases = set(parent.get('case_ids') or [])
    if len(cases) < 2 * decomposition.LEAF_MIN_CASES:
        return None  # fewer cases than two leaves: the root is one leaf, confirmed as atomic
    ref = parent.get('feature_inventory_ref') or decomposition.assigned_module(s, parent).get('feature_inventory_ref')
    require(ref, 'a split is cut from the feature inventory the root was registered with')
    features = {fid: f for fid, f in keyed(read_json(check_ref(ref)).get('features'), 'feature_id').items()
                if cases & set(f.get('case_ids') or [])}
    require(features, 'the inventory holds no feature of this root')
    taken = {int(k[1:]) for k in (*s['modules'], *s.get('module_groups', {})) if k[1:].isdigit()}
    scope = parent.get('scope') or {}
    children = []
    for n, (paths, fids) in enumerate(groups(features, cases, decomposition.LEAF_MIN_CASES, decomposition.LEAF_MAX_CASES), 1):
        held = sorted({c for fid in fids for c in features[fid]['case_ids']} & cases)
        number = max(taken | {0}) + n
        children.append({
            'module_id': f'M{number:03d}', 'name': paths[0].split('/')[-1], 'kind': 'feature', 'functional_paths': sorted(paths),
            'case_ids': held, 'dependencies': [], 'write_paths': list(parent.get('write_paths') or []),
            'scope': {'in': [features[fid].get('name') or fid for fid in fids], 'out': [],
                      'requirement_ids': sorted({r for fid in fids for r in features[fid].get('requirement_ids') or []}
                                                & set(scope.get('requirement_ids') or []))},
            'context_refs': list(parent.get('context_refs') or []),
            **({'dimension_analysis_ref': todo('本叶四维分析引用'), 'anchor_ui': todo('本叶验收的页面')} if s.get('dimension_slicing_required') else {}),
            **({'behavior_review': todo('行为评审：入口、可观察结果、生产接线、边界理由、验证')} if s.get('behavior_contract_required') else {})})
    return {'parent_module_id': mid, 'kind': 'split', 'feature_inventory_ref': ref,
            'rationale': f'按功能树切分：共同前缀下一级节点各为一叶，用例超过 {decomposition.LEAF_MAX_CASES} 条的节点再下切一级，'
                         f'共享用例的节点合为一叶，不足 {decomposition.LEAF_MIN_CASES} 条的并入最小的另一叶；写范围按叶收窄',
            'children': children}


def write(root, mid, out):
    import ledger
    s, _ = ledger.read_events(root)
    require(s, 'run not initialised')
    out = Path(out)
    require(out.is_absolute(), 'absolute output directory required')
    plan = draft(s, mid)
    if plan is None:
        return {'module_id': mid, 'draft': None, 'next_action': 'fewer cases than two leaves: submit decompose with kind atomic-leaf'}
    path = out / 'decomposition-draft.json'
    require(not path.exists(), 'refusing to overwrite ' + str(path))
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    return {'module_id': mid, 'draft': file_ref(path), 'children': [c['module_id'] for c in plan['children']],
            'unfilled': path.read_text().count(SKELETON_MARK),
            'next_action': 'edit the leaves (names, write paths, marked parts), then submit decompose with this file as plan_ref'}


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
