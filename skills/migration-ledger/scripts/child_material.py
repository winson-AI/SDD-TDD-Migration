"""What a split's children are given when the orchestrator only says where to cut.

A child that names no four-dimension analysis gets one cut from its parent's: every parent item with a case the child
holds, under the child's id, tracing to the item it came from, keeping its conditions and its evidence, holding only the
child's cases; the API and data contracts go with the first child that takes an item citing them. A child that names no
behaviour review gets one drafted from the features it holds and the parent's own review: entry and observable result
from the inventory, coverage, acceptance owner and providers from its allocation, binding and rationale from the parent.
A split that needs a partition review and names none gets the Ledger's. What a child writes itself is kept and judged
as written. The completed split is stored under reports/allocations and is the one the Ledger accepts.
"""
import copy
import json
from pathlib import Path

from contracts import check_ref, digest, file_ref, keyed, read_json

KINDS = (('api_ids', 'api_inventory_ref', 'api_review', 'calls', 'api_id'),
         ('data_ids', 'data_inventory_ref', 'data_review', 'entities', 'data_id'))


def write(path, value):
    """The reference of `value` written beside `path` under a name that carries its digest: a later split never
    overwrites what an earlier one stored."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    path = path.with_name(f'{path.stem}-{digest(text)[:12]}{path.suffix}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text)
    return file_ref(path)


def analysis(parent_data, child, owners, out):
    """The child's four-dimension analysis cut from the parent's; `owners` names, per parent item, the child that carries its
    API and data contracts."""
    mid, cases = child['module_id'], set(child['case_ids'])
    data = {key: copy.deepcopy(value) for key, value in parent_data.items() if key not in ('dimensions', 'scope')}
    data.update(module_id=mid, unresolved=[], dimensions=[])
    renamed, contracts = {}, {kind: set() for kind, *_ in KINDS}
    for row in parent_data['dimensions']:
        new = {key: copy.deepcopy(value) for key, value in row.items() if key not in ('items', 'condition_review')}
        items = []
        for item in row.get('items') or [] if row.get('status') == 'applicable' else []:
            held = [cid for cid in item['case_ids'] if cid in cases]
            if not held:
                continue
            renamed[item['item_id']] = mid + '-' + item['item_id']
            copied = {**copy.deepcopy(item), 'item_id': renamed[item['item_id']], 'case_ids': held, 'parent_item_ids': [item['item_id']]}
            for kind, *_ in KINDS:
                if owners.get(item['item_id']) == mid:
                    contracts[kind].update(item.get(kind) or [])
                else:
                    copied.pop(kind, None)  # a contract has one owner among the children
            items.append(copied)
        if items or (row.get('status') == 'applicable' and row.get('copy_plan_ref') and not row.get('items') and owners.get(('rows', row['dimension'])) == mid):
            new['items'] = items
            if row.get('condition_review'):
                new['condition_review'] = {facet: {**value, 'condition_refs': [{**ref, 'item_id': renamed[ref['item_id']]}
                                                   for ref in value.get('condition_refs') or [] if ref.get('item_id') in renamed]}
                                           for facet, value in row['condition_review'].items()}
        else:
            for key in ('copy_plan_ref', 'parameter_sheet_ref'):
                new.pop(key, None)
            new.update(status='not-applicable', items=[], reason=f'{mid} holds no case of the parent items of this dimension')
        data['dimensions'].append(new)
    for kind, ref_key, review_key, rows_key, id_key in KINDS:
        if not parent_data.get(ref_key):
            continue
        inventory = read_json(check_ref(parent_data[ref_key]))
        mine = contracts[kind]
        if mine:
            data[ref_key] = write(out / f'{mid}-{rows_key}.json', {
                'schema_version': 1, 'module_id': mid,
                rows_key: [row for row in inventory.get(rows_key) or [] if row.get(id_key) in mine],
                'contracts': [row for row in inventory.get('contracts') or [] if row.get(id_key) in mine], 'exclusions': []})
        else:
            data.pop(ref_key, None)
            if data.get(review_key):
                data[review_key] = {**data[review_key], 'status': 'not-applicable',
                                    'reason': f'{mid} takes no item that cites one of the parent\'s contracts'}
    data['scope'] = copy.deepcopy(child.get('scope'))
    return data


def review(parent, child, features):
    """The child's behaviour review drafted from the features it holds and its parent's review."""
    held = [f for f in features if set(f.get('case_ids') or []) & set(child['case_ids'])]
    base = parent.get('behavior_review') or {}
    said = lambda key, fallback: '；'.join(dict.fromkeys(f[key] for f in held if f.get(key))) or base.get(fallback) or fallback
    evidence = list(base.get('evidence_refs') or []) + [ref for f in held for ref in f.get('evidence_refs') or []]
    return {'scope_sha256': digest(child.get('scope')), 'entry': said('trigger', 'entry'),
            'observable_result': said('observable_result', 'observable_result'),
            'production_binding': base.get('production_binding') or 'the parent root binds this flow',
            'boundary_rationale': 'the feature-tree nodes %s: one sub-business flow of %s' % (', '.join(child.get('functional_paths') or [child['module_id']]), parent['module_id']),
            'requirement_ids': list(child['scope']['requirement_ids']), 'case_ids': list(child['case_ids']),
            'shared_capabilities': [], 'unresolved': [], 'evidence_refs': list({ref['path']: ref for ref in evidence}.values()),
            'verification': {'acceptance_owner': child['module_id'], 'independent_observation': said('observable_result', 'observable_result'),
                             'isolation_strategy': 'the frozen tests of the leaf with stand-ins for what its providers offer',
                             'integration_responsibility': 'the leaf integrates its providers\' accepted code',
                             'case_ids': list(child['case_ids']), 'integration_case_ids': [],
                             'provider_inputs': [{'module_id': dep} for dep in child.get('dependencies') or []]}}


def complete(s, parent, plan, root, name):
    """(plan, ref of the completed plan or None): the split with what its children did not write cut by the Ledger."""
    if plan.get('kind') == 'atomic-leaf' or root is None:
        return plan, None
    import decomposition
    plan, out = copy.deepcopy(plan), Path(root) / 'reports/allocations'
    parent_ref = parent.get('dimension_analysis_ref')
    parent_data = read_json(check_ref(parent_ref)) if parent_ref and s.get('dimension_slicing_required') else None
    ref = plan.get('feature_inventory_ref') or parent.get('feature_inventory_ref')
    try:
        features = list(keyed(read_json(check_ref(ref)).get('features'), 'feature_id').values()) if ref else []
    except (ValueError, OSError, KeyError, TypeError):
        features = []
    fresh = [c for c in plan.get('children') or [] if isinstance(c, dict) and c.get('module_id') and not decomposition.registered(s, c)]
    owners = {}
    if parent_data is not None:
        for row in parent_data['dimensions']:
            for item in row.get('items') or [] if row.get('status') == 'applicable' else []:
                holder = next((c['module_id'] for c in fresh if set(item['case_ids']) & set(c.get('case_ids') or [])), None)
                owners.setdefault(item['item_id'], holder)
            if row.get('status') == 'applicable' and row.get('copy_plan_ref') and not row.get('items') and fresh:
                owners[('rows', row['dimension'])] = fresh[0]['module_id']
    changed = False
    for child in fresh:
        child.setdefault('scope', {'in': [child.get('name') or child['module_id']], 'out': [],
                                   'requirement_ids': list((parent.get('scope') or {}).get('requirement_ids') or [])})
        excluded = child['scope'].setdefault('out', [])  # the parent's exclusions, before the analysis and review bind the scope
        excluded += [line for line in (parent.get('scope') or {}).get('out') or [] if line not in excluded]
        if parent_data is not None and not child.get('dimension_analysis_ref'):
            derived = analysis(parent_data, child, owners, out)
            derived['parent_ref'] = parent_ref
            child['scope']['requirement_ids'] = sorted({r for row in derived['dimensions'] for item in row.get('items') or [] for r in item['requirement_ids']}) \
                or child['scope']['requirement_ids']
            derived['scope'] = copy.deepcopy(child['scope'])
            child['dimension_analysis_ref'] = write(out / f"{child['module_id']}-dimensions.json", derived)
            changed = True
        if s.get('behavior_contract_required') and not child.get('behavior_review'):
            child['behavior_review'] = review(parent, child, features)
            changed = True
    if s.get('behavior_contract_required') and 'case_acceptance' not in plan:
        from behavior_contract import accepts
        holders = {cid: [c['module_id'] for c in plan.get('children') or [] if cid in (c.get('case_ids') or [])] for cid in accepts(parent)}
        if all(len(mids) == 1 for mids in holders.values()):  # one holder per case: it is the slice that accepts it
            plan['case_acceptance'] = {cid: mids[0] for cid, mids in holders.items()}
            changed = True
    if changed and parent_data is not None and not plan.get('dimension_partition_review_ref'):
        plan['dimension_partition_review_ref'] = write(out / f"{parent['module_id']}-partition.md",
            'Ledger partition: each parent item goes to the children holding its cases, under the child\'s id and with only their '
            'cases; its API and data contracts go with the first of them.\n')
        changed = True
    if not changed:
        return plan, None
    return plan, write(out / name, plan)
