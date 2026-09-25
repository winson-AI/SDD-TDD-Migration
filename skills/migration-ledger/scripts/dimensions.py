"""Evidence-backed UI/Logic/Adhesive/Resource allocation and task coverage.

Structural gates only: agents still review semantic fidelity and completeness.
"""
from pathlib import Path

from contracts import check_ref, digest, keyed, nonempty, read_json, require

ORDER = ['UI', 'Logic', 'Adhesive', 'Resource']
SOURCES = ('legacy', 'architecture', 'reuse', 'target')


def evidence(refs, label):
    for ref in nonempty(refs, label):
        check_ref(ref)


def load(ref, module_id):
    data = read_json(check_ref(ref))
    require(data.get('schema_version') == 1 and data.get('module_id') == module_id,
            'dimension analysis module/schema mismatch')
    if data.get('parent_ref'):
        check_ref(data['parent_ref'])
    require(data.get('unresolved') == [], 'dimension uncertainty requires clarification before allocation/freeze')
    reviews = data.get('source_reviews', {})
    require(set(reviews) == set(SOURCES), 'dimensions require legacy/architecture/reuse/target review')
    for name, review in reviews.items():
        require(review.get('conclusion'), 'dimension source review conclusion required: ' + name)
        evidence(review.get('evidence_refs'), 'dimension source review evidence')
    rows = data.get('dimensions', [])
    require([row.get('dimension') for row in rows] == ORDER, 'dimension analysis order must be UI -> Logic -> Adhesive -> Resource')
    items = {}
    for row in rows:
        require(row.get('status') in ('applicable', 'not-applicable'), 'dimension status unresolved')
        require(row.get('reason'), 'dimension applicability rationale required')
        evidence(row.get('evidence_refs'), 'dimension applicability evidence')
        if row['status'] == 'not-applicable':
            require(row.get('items') == [], 'N/A dimension cannot contain work items')
            continue
        for iid, item in keyed(row.get('items'), 'item_id').items():
            require(iid not in items, 'duplicate dimension item')
            require(all(item.get(k) for k in ('behavior', 'source_locator', 'target_strategy', 'target_binding', 'acceptance')),
                    'dimension item needs source, behavior, target binding and acceptance')
            require(item['target_strategy'] in ('reuse', 'adapt', 'reference', 'new'), 'invalid dimension target strategy')
            nonempty(item.get('requirement_ids'), 'dimension requirements')
            nonempty(item.get('case_ids'), 'dimension cases')
            evidence(item.get('evidence_refs'), 'dimension item evidence')
            if row['dimension'] == 'Resource':
                for field in ('source_resource', 'target_resource', 'consumer', 'conversion', 'qualifiers'):
                    require(item.get(field), 'resource mapping missing ' + field)
            items[iid] = {**item, 'dimension': row['dimension']}
    require(items, 'functional module must contain applicable dimension work')
    import semantics
    semantics.validate_items(items)
    return data, items


def allocation(s, module):
    ref = module.get('dimension_analysis_ref')
    if not s.get('dimension_slicing_required') and not ref:
        return {}
    data, items = load(ref, module['module_id'])
    require(module.get('scope') and data.get('scope') == module['scope'],
            'dimension analysis must bind the already allocated module scope')
    allowed = set(module.get('scope', {}).get('requirement_ids', s['requirement_ids']))
    require({rid for item in items.values() for rid in item['requirement_ids']} == allowed,
            'dimension allocation must cover scoped requirements')
    require({cid for item in items.values() for cid in item['case_ids']} == set(module['case_ids']),
            'dimension allocation must cover scoped cases')
    return items


def partition(s, parent, plan):
    expected = allocation(s, parent)
    if not expected:
        return
    # This review explains disjoint responsibilities when a coarse parent item
    # is refined into multiple subfunctions; shared code still has one writer.
    check_ref(plan.get('dimension_partition_review_ref'))
    covered, child_ids = set(), set()
    coverage = {iid: {'requirements': set(), 'cases': set()} for iid in expected}
    for child in plan['children']:
        items = allocation({**s, 'dimension_slicing_required': True}, child)
        data, _ = load(child['dimension_analysis_ref'], child['module_id'])
        require(data.get('parent_ref') == parent['dimension_analysis_ref'], 'child dimension parent reference mismatch')
        for iid, item in items.items():
            require(iid not in child_ids, 'dimension item ownership duplicated across children')
            child_ids.add(iid)
            origins = set(nonempty(item.get('parent_item_ids'), 'child dimension parent item trace'))
            require(origins <= set(expected), 'unknown parent dimension item; revise GO scope first')
            require(all(expected[pid]['dimension'] == item['dimension'] for pid in origins), 'child dimension changed')
            require(set(item['requirement_ids']) <= {r for pid in origins for r in expected[pid]['requirement_ids']}
                    and set(item['case_ids']) <= {c for pid in origins for c in expected[pid]['case_ids']},
                    'child dimension requirement/case outside parent item')
            covered.update(origins)
            for pid in origins:
                coverage[pid]['requirements'].update(item['requirement_ids'])
                coverage[pid]['cases'].update(item['case_ids'])
    require(covered == set(expected), 'child dimensions omit parent work (N/A cannot discard inherited work)')
    for iid, item in expected.items():
        require(set(item['requirement_ids']) <= coverage[iid]['requirements'] and
                set(item['case_ids']) <= coverage[iid]['cases'], 'child dimensions omit parent item requirements/cases')


def validate_plan(plan, module):
    ref = module.get('dimension_analysis_ref')
    if not ref and not plan.get('dimension_analysis_ref'):
        return
    require(ref and plan.get('dimension_analysis_ref') == ref, 'SPEC must bind allocated dimension analysis')
    _, items = load(ref, module['module_id'])
    traces = keyed(plan.get('dimension_trace'), 'item_id')
    require(set(traces) == set(items), 'SPEC dimension trace must cover every allocated item')
    tasks = {t['task_id']: t for t in plan['tasks']}
    paths = {p['path_id']: p for p in plan['paths']}
    for iid, trace in traces.items():
        tids = set(nonempty(trace.get('task_ids'), 'dimension tasks'))
        pids = set(nonempty(trace.get('path_ids'), 'dimension paths'))
        require(tids <= set(tasks) and pids <= set(paths), 'dimension trace references unknown task/path')
        require(pids <= {p for tid in tids for p in tasks[tid]['path_ids']}, 'dimension path not covered by mapped task')
        require(set(items[iid]['requirement_ids']) <= {r for tid in tids for r in tasks[tid].get('global_requirement_ids', tasks[tid]['requirement_ids'])},
                'dimension task requirement trace incomplete')
        require(set(items[iid]['case_ids']) <= {paths[pid]['case_id'] for pid in pids if paths[pid].get('kind') != 'build'},
                'dimension behavior requires case paths; build alone is not fidelity')
        pairs = nonempty(trace.get('assertions'), 'dimension assertion trace')
        require({a.get('path_id') for a in pairs} == pids, 'dimension paths need assertion trace')
        for pair in pairs:
            require(pair.get('assertion_id') in {a['assertion_id'] for a in paths[pair['path_id']]['expected_assertions']},
                    'unknown dimension assertion')
    require({tid for trace in traces.values() for tid in trace['task_ids']} == set(tasks), 'task missing dimension ownership')
    task_analyses(plan, module, items, traces)
    # The machine mapping complements, never replaces, normative OpenSpec text.
    for kind in ('design', 'spec', 'tasks'):
        text = '\n'.join(check_ref(d).read_text() for d in plan['definitions'] if d['kind'] == kind)
        require(all(iid in text for iid in items), 'OpenSpec ' + kind + ' missing dimension item IDs')



def task_analyses(plan, module, items, traces):
    """Partition task scope first; dimension analysis then defines implementation."""
    for task in plan['tasks']:
        scope = task.get('scope', {})
        nonempty(scope.get('in'), 'task business scope')
        require(isinstance(scope.get('out'), list), 'task exclusions required')
        require(set(module['scope']['out']) <= set(scope['out']), 'task must retain module exclusions')
        writes = nonempty(scope.get('write_paths'), 'task write scope')
        require(all(Path(p).is_absolute() and any(Path(p).resolve().is_relative_to(Path(m).resolve())
                    for m in module['write_paths']) for p in writes), 'task write scope outside assigned module')
        analysis = task.get('dimension_analysis', {})
        require(analysis.get('scope_sha256') == digest(scope), 'task dimension analysis must bind current task scope')
        require(analysis.get('parent_ref') == plan['dimension_analysis_ref'], 'task dimension analysis parent mismatch')
        require(analysis.get('unresolved') == [], 'task dimension uncertainty requires clarification')
        rows = analysis.get('dimensions', [])
        require([row.get('dimension') for row in rows] == ORDER, 'task dimension analysis order incomplete')
        for row in rows:
            expected = {iid for iid, trace in traces.items()
                        if task['task_id'] in trace['task_ids'] and items[iid]['dimension'] == row['dimension']}
            ids = row.get('item_ids')
            require(isinstance(ids, list) and len(set(ids)) == len(ids) and set(ids) == expected,
                    'task dimension items differ from allocated trace')
            require(row.get('status') == ('applicable' if expected else 'not-applicable'),
                    'task N/A cannot discard allocated implementation')
            require(row.get('reason'), 'task dimension applicability rationale required')
            evidence(row.get('evidence_refs'), 'task dimension evidence')
            if expected:
                require(row.get('implementation'), 'task dimension needs concrete implementation guidance')


def verify(plan):
    if plan.get('dimension_analysis_ref'):
        load(plan['dimension_analysis_ref'], plan['module_id'])
        for task in plan['tasks']:
            analysis = task.get('dimension_analysis', {})
            require([row.get('dimension') for row in analysis.get('dimensions', [])] == ORDER,
                    'frozen task dimension analysis missing; replan and refreeze')
            require(analysis.get('scope_sha256') == digest(task.get('scope')), 'frozen task scope changed')
            for row in analysis['dimensions']:
                evidence(row.get('evidence_refs'), 'frozen task dimension evidence')


def implementation(plan, result):
    if not plan.get('dimension_analysis_ref'):
        return
    _, items = load(plan['dimension_analysis_ref'], plan['module_id'])
    traces = keyed(result.get('dimension_evidence'), 'item_id')
    require(set(traces) == set(items), 'implementation dimension evidence incomplete')
    import semantics
    semantics.implementation(items, traces)
    planned = {t['item_id']: t for t in plan['dimension_trace']}
    tasks = {t['task_id']: t for t in plan['tasks']}
    for trace in result.get('task_trace', []):
        allowed = tasks[trace['task_id']]['scope']['write_paths']
        require(all(any(Path(f).resolve().is_relative_to(Path(p).resolve()) for p in allowed)
                    for f in trace.get('files', [])), 'implementation file outside planned task scope')
    for iid, trace in traces.items():
        require(set(trace.get('task_ids', [])) == set(planned[iid]['task_ids']), 'implementation dimension task mismatch')
        require(trace.get('summary'), 'dimension implementation summary required')
        evidence(trace.get('evidence_refs'), 'dimension implementation evidence')
        # Reused assets need not be modified, but must have real production consumers.
        if items[iid]['dimension'] == 'Resource':
            for field, ref_field in (('target_resource', 'target_resource_ref'), ('consumer', 'consumer_ref')):
                actual = check_ref(trace.get(ref_field))
                expected = Path(items[iid][field].split('#', 1)[0])
                require(expected.is_absolute() and actual.resolve() == expected.resolve(), 'resource evidence differs from planned ' + field)


def current(module, mutable_paths=()):
    """Keep reused, unchanged resource/consumer evidence live after acceptance."""
    if not module.get('code_files'):
        return
    def verify(ref):
        path = Path(ref['path'])
        if any(path.is_relative_to(Path(p).resolve()) for p in mutable_paths):
            from run_storage import checked_path
            checked_path(path)
        else:
            check_ref(ref)
    for trace in module.get('dimension_evidence', []):
        for ref in trace['evidence_refs']:
            verify(ref)
        for field in ('target_resource_ref', 'consumer_ref'):
            if trace.get(field):
                verify(trace[field])
