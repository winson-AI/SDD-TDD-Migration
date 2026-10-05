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


def build(s, events):
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
        rows[mid] = {'events': counts['events'], 'dispatches': counts['dispatches'],
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
    return {'modules': rows, 'totals': totals}
