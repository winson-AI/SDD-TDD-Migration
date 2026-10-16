"""The target's state before the migration, per feature: absent, shell-only, partial or existing, with evidence.

GO records it at global discovery and binds it to the global plan; the split sets a scaffold only where the shell is
missing, a leaf whose target already holds code reuses or adapts it (or says why not), and the report shows the
state each feature started from."""
from pathlib import Path

from contracts import check_ref, nonempty, owed, read_json, require

STATES = ('absent', 'shell-only', 'partial', 'existing')
MISSING_SHELL = ('absent', 'shell-only')
HOLDS_CODE = ('partial', 'existing')


def check(s, plan):
    """The profile the global plan binds: one row per feature of the inventory (or per module without one), a known
    state, evidence, and absolute `path#symbol` locations wherever the target holds code."""
    ref = plan.get('target_profile_ref')
    if not ref:
        return None
    data = read_json(check_ref(ref))
    require(data.get('schema_version') == 1 and isinstance(data.get('target_root'), str)
            and Path(data['target_root']).resolve() == Path(s['target_root']).resolve(), 'target profile schema/target mismatch')
    rows = data.get('features')
    require(isinstance(rows, list) and rows, 'target profile lists features')
    seen = set()
    for row in rows:
        key = row.get('feature_id') or row.get('module_id')
        require(isinstance(key, str) and key and key not in seen, 'target profile row needs a unique feature_id or module_id')
        seen.add(key)
        require(row.get('state') in STATES, 'target state is one of ' + ', '.join(STATES) + ': ' + key)
        for ev in nonempty(row.get('evidence_refs'), 'target profile evidence for ' + key):
            check_ref(ev)
        if row['state'] != 'absent':
            for symbol in nonempty(row.get('symbols'), 'target symbols the state rests on: ' + key):
                require(isinstance(symbol, str) and '#' in symbol and Path(symbol.split('#', 1)[0]).is_absolute(), 'target symbol is absolute path#symbol: ' + key)
    inventory = plan.get('feature_inventory_ref')
    if inventory:
        features = {f['feature_id'] for f in read_json(check_ref(inventory)).get('features') or []}
        require(features <= seen, 'target profile omits features: ' + ', '.join(sorted(features - seen)))
    return data


def rows(s):
    """{feature_id or module_id: row} of the accepted profile; empty when the run recorded none."""
    ref = ((s.get('global_plan') or {}).get('content') or {}).get('target_profile_ref') or next(
        (m['target_profile_ref'] for m in [*s.get('modules', {}).values(), *s.get('module_groups', {}).values()] if m.get('target_profile_ref')), None)
    if not ref:
        return {}
    try:
        return {row.get('feature_id') or row.get('module_id'): row for row in read_json(check_ref(ref)).get('features') or []}
    except (ValueError, OSError, KeyError, TypeError):
        return {}


def of_module(s, module):
    """The profile rows a leaf's features (or the leaf itself) start from."""
    held = rows(s)
    if not held:
        return []
    import decomposition
    owners = ((s.get('global_plan') or {}).get('content') or {}).get('feature_owners', {})
    mine = {fid for fid, who in owners.items() if module['module_id'] in who} | {module['module_id']}
    return [held[key] for key in sorted(mine) if key in held]


def shell_missing(s, parent):
    """Whether any feature the parent splits starts from a target without a shell; None when no profile was recorded."""
    held = rows(s)
    if not held:
        return None
    owners = ((s.get('global_plan') or {}).get('content') or {}).get('feature_owners', {})
    import decomposition
    leaves = set(decomposition.leaves(s, parent['module_id'])) | {parent['module_id']}
    mine = [held[fid] for fid, who in owners.items() if set(who) & leaves and fid in held] or [held[k] for k in held if k in leaves]
    if not mine and parent.get('target_profile_ref'):  # before the global plan: the profile the root itself brought covers its features
        mine = list(held.values())
    return any(row['state'] in MISSING_SHELL for row in mine) if mine else None


def freeze(s, m):
    """A leaf whose target already holds code for its features reuses or adapts it, or records why not: owed, not refused."""
    code = [row for row in of_module(s, m) if row['state'] in HOLDS_CODE]
    if not code:
        return
    plan = m.get('plan') or {}
    reused = False
    if plan.get('reuse_plan_ref'):
        try:
            review = read_json(check_ref(plan['reuse_plan_ref']))
            caps = {c['capability_id']: c for c in read_json(check_ref(review['catalog_ref'])).get('capabilities', [])}
            reused = any(r.get('decision') in ('reuse', 'adapt') and caps.get(r.get('capability_id'), {}).get('source_id') == 'TARGET'
                         for r in review.get('mappings', []))
        except (ValueError, OSError, KeyError, TypeError):
            reused = False
    if not reused and plan.get('dimension_analysis_ref'):
        try:
            analysis = read_json(check_ref(plan['dimension_analysis_ref']))
            for key in ('data_inventory_ref', 'api_inventory_ref'):
                if analysis.get(key):
                    reused = reused or any(isinstance(row, dict) and row.get('existing_target') for row in read_json(check_ref(analysis[key])).get('contracts', []))
        except (ValueError, OSError, KeyError, TypeError):
            pass
    owed(reused, 'the target already holds %s code for %s: reuse or adapt it (a TARGET mapping or an existing_target contract), or record why not'
         % (', '.join(sorted({row['state'] for row in code})), ', '.join(row.get('feature_id') or row.get('module_id') for row in code)))


def report(s):
    owners = ((s.get('global_plan') or {}).get('content') or {}).get('feature_owners', {})
    return [{'key': key, 'state': row['state'], 'modules': sorted(owners.get(key, [key] if key in s['modules'] else [])),
             'entry_points': list(row.get('entry_points') or []), 'tests': bool(row.get('tests')), 'symbols': len(row.get('symbols') or [])}
            for key, row in sorted(rows(s).items())]
