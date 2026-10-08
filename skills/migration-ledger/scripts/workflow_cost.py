"""Workflow cost per module, derived from the committed journal: what the ceremony actually cost.

Counts are evidence for trimming the process, not gates. Dispatches are worker assignments
(a build assignment continuing into static review is one dispatch); human gates are human
decisions bound to the module or to its parent's batch envelope.
"""
from collections import Counter
import json
from pathlib import Path


def journal(root):
    path = Path(root) / 'ledger/events.jsonl'
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def plan_volume(plan, resolve=None):
    """What planning a leaf cost before any code: the files written for the plan (its definitions and whatever its
    author staged) apart from the sources it only cites, each as (files, bytes). `resolve` finds a referenced file
    where it is kept now, so the numbers do not change when evidence is archived."""
    from contracts import check_ref
    found = {}
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
                found[value['path']] = value
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(plan or {})
    defined = {ref.get('path') for ref in (plan or {}).get('definitions') or [] if isinstance(ref, dict)}
    volume = {'authored': [0, 0], 'cited': [0, 0]}
    for path, ref in found.items():
        row = volume['authored' if path in defined or '/staging/' in path else 'cited']
        row[0] += 1
        try:
            row[1] += Path((resolve or check_ref)(ref)).stat().st_size
        except (ValueError, OSError):
            pass  # a missing file is the drift gates' concern; the count still includes it
    return {key: tuple(row) for key, row in volume.items()}


def decision_uses(events):
    """{decision_id: [(operation, module_id)]}: the events, other than the decision itself, that spent a decision or
    drew on it. Read from the journal, so it also holds for decisions made before anyone asked what they were for."""
    uses = {}
    for event in events:
        if event.get('operation') == 'decision':
            continue
        for did, change in (((event.get('patch') or {}).get('set') or {}).get('decisions') or {}).items():
            if isinstance(change, dict) and (change.get('consumed') or 'used_by' in change):
                uses.setdefault(did, []).append((event['operation'], event.get('module_id')))
    return uses


def human_touches(s, events=()):
    """Every human decision of the run with what it was used for; a decision that released a blocker carries its reason."""
    released = {digest_ref(row.get('resolution_ref')): row.get('reason') for m in s['modules'].values() for row in m.get('blocker_history', [])}
    uses = decision_uses(events)
    rows = []
    for did, d in sorted(s.get('decisions', {}).items()):
        spent = uses.get(did, [])
        purpose = '、'.join(dict.fromkeys(op for op, _ in spent)) or ('used' if d.get('consumed') or d.get('used_by') else 'unused')
        rows.append({'decision_id': did, 'module_id': d.get('module_id'), 'used_for': purpose, 'uses': len(spent),
                     'used_by_modules': sorted({mid for _, mid in spent if mid}),
                     'reason': released.get(digest_ref(d.get('human_source_ref')))})
    return rows


def digest_ref(ref):
    return (ref or {}).get('path'), (ref or {}).get('sha256')


def build(s, events, resolve=None):
    per_module = {mid: Counter() for mid in s['modules']}
    global_ops = Counter()
    for e in events:
        mid, op = e.get('module_id'), e.get('operation')
        if mid in per_module:
            per_module[mid]['events'] += 1
            per_module[mid]['dispatches'] += op == 'assign'
            per_module[mid]['context_receipts'] += op == 'context-submit'
            per_module[mid]['acceptances'] += op in ('accept', 'diagnosis-accept', 'freeze', 'complete')
        elif mid is None:
            global_ops[op] += 1
    human = Counter()
    for d in s.get('decisions', {}).values():
        owner = d.get('module_id')
        targets = d.get('used_by') if d.get('kind') == 'batch-envelope' else [owner]
        for mid in targets or []:
            human[mid] += 1
    rows = {}
    for mid, counts in per_module.items():
        m = s['modules'][mid]
        volume = plan_volume(m.get('plan'), resolve)
        rows[mid] = {'cases': len(m.get('case_ids', [])), 'tasks': len((m.get('plan') or {}).get('tasks', [])),
                     'plan_documents': volume['authored'][0], 'plan_bytes': volume['authored'][1],
                     'cited_documents': volume['cited'][0], 'cited_bytes': volume['cited'][1],
                     'events': counts['events'], 'dispatches': counts['dispatches'],
                     'context_receipts': counts['context_receipts'], 'acceptances': counts['acceptances'],
                     'human_decisions': human[mid], 'fix_rounds': m.get('total_fix_rounds', 0),
                     'local_fix_used': m.get('local_fix_used', 0), 'lean_leaf': bool(m.get('lean_leaf')),
                     'card_dispatches': m.get('card_load', {}).get('dispatches', 0),
                     'card_bytes_full': m.get('card_load', {}).get('full', 0),
                     'card_bytes_delivered': m.get('card_load', {}).get('delivered', 0)}
    totals = {k: sum(r[k] for r in rows.values()) for k in
              ('events', 'dispatches', 'context_receipts', 'acceptances', 'human_decisions', 'fix_rounds',
               'card_dispatches', 'card_bytes_full', 'card_bytes_delivered')}
    totals['global_events'] = sum(global_ops.values())
    totals['audit_dispatches'] = global_ops['audit-assign']
    touches = human_touches(s, events)
    return {'modules': rows, 'totals': totals, 'human_touches': touches,
            'human_by_purpose': dict(Counter(row['used_for'] for row in touches))}
