"""Evidence-backed UI/Logic/Adhesive/Resource allocation and task coverage.

Structural gates only: agents still review semantic fidelity and completeness.

An analysis is judged once, when the Ledger registers it (`judge`). Every later step reads it (`load`): only drift of
its bytes or of what it cites can refuse it then. A rule about the content of an analysis therefore belongs in `judge`,
and code that reads an analysis must not assume a field `judge` came to require later.
"""
from pathlib import Path

from contracts import check_ref, digest, intact, keyed, nonempty, read_json, require

ORDER = ['UI', 'Logic', 'Adhesive', 'Resource']
SOURCES = ('legacy', 'architecture', 'reuse', 'target')
CONDITION_FACETS = {'UI': ('theme', 'density', 'font-scale', 'loading-error', 'visibility-layout'),
                    'Resource': ('theme', 'density', 'loading-error')}


def evidence(refs, label):
    for ref in nonempty(refs, label):
        check_ref(ref)


def load(ref, module_id):
    """A registered analysis and its items, as accepted."""
    data = read_json(check_ref(ref))
    require(data.get('schema_version') == 1 and data.get('module_id') == module_id,
            'dimension analysis module/schema mismatch')
    return intact(lambda: judge(ref, module_id)) or (
        data, {item['item_id']: {**item, 'dimension': row['dimension']} for row in data.get('dimensions', [])
               if row.get('status') == 'applicable' for item in row.get('items') or []})


def judge(ref, module_id):
    """Every content rule of an analysis the Ledger is asked to register."""
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
        require(row.get('copy_plan_ref') is None or (row['dimension'] == 'Resource' and row['status'] == 'applicable'),
                'a copy plan belongs to an applicable Resource dimension')
        require(row.get('parameter_sheet_ref') is None or (row['dimension'] == 'UI' and row['status'] == 'applicable'),
                'a parameter sheet belongs to an applicable UI dimension')
        if row['status'] == 'not-applicable':
            require(row.get('items') == [], 'N/A dimension cannot contain work items')
            continue
        if row.get('parameter_sheet_ref'):
            check_ref(row['parameter_sheet_ref'])
        if row.get('copy_plan_ref'):
            check_ref(row['copy_plan_ref'])
            if row.get('items') == []:
                continue  # everything this module's UI needs travels by path; nothing is left to author
        for iid, item in keyed(row.get('items'), 'item_id').items():
            require(iid not in items, 'duplicate dimension item')
            require(all(item.get(k) for k in ('behavior', 'source_locator', 'target_strategy', 'target_binding', 'acceptance')),
                    'dimension item needs source, behavior, target binding and acceptance')
            require(item['target_strategy'] in ('reuse', 'adapt', 'reference', 'new', 'subclosure-port', 'capture-fixture'), 'invalid dimension target strategy')
            if item['target_strategy'] == 'capture-fixture':
                require(item.get('replaceable_boundary'), 'capture-fixture requires a replaceable repository/datasource boundary')
            nonempty(item.get('requirement_ids'), 'dimension requirements')
            nonempty(item.get('case_ids'), 'dimension cases')
            evidence(item.get('evidence_refs'), 'dimension item evidence')
            fidelity_conditions(item)
            if row['dimension'] == 'Resource':
                require(not (item.get('source_signal') and item.get('source_resource')),
                        'a Resource item names a resource file or a recorded image source, not both')
                # An image source without a file (a URL, a run-time name, drawing code) has no qualifier family.
                fields = ('target_resource', 'consumer', 'conversion') + (
                    ('source_signal',) if item.get('source_signal') else ('source_resource', 'qualifiers'))
                for field in fields:
                    require(item.get(field), 'resource mapping missing ' + field)
                import resource_fidelity
                resource_fidelity.validate_item(item)
                resource_fidelity.consumers(item)
            items[iid] = {**item, 'dimension': row['dimension']}
    require(items, 'functional module must contain applicable dimension work')
    coverage_review(data)
    import semantics
    semantics.validate_items(items)
    import api_contract
    api_contract.load(data, items)
    return data, items


def fidelity_conditions(item, paths=None, trace=None):
    """Source-backed conditions share the existing PATH/ASSERT chain; presence is not proof."""
    rows = item.get('fidelity_conditions', [])
    require(isinstance(rows, list), 'fidelity_conditions must be a list')
    for row in (keyed(rows, 'condition_id').values() if rows else []):
        require(row.get('condition') and row.get('reason') and row.get('status') in ('applicable', 'not-applicable'),
                'fidelity condition needs applicability and rationale')
        evidence(row.get('evidence_refs'), 'fidelity condition source evidence')
        if row['status'] == 'not-applicable':
            require(row.get('assertions') == [], 'excluded fidelity condition cannot claim assertions')
            continue
        if paths is None: continue  # GO/parent records conditions; leaf planning binds actual assertions.
        for pair in nonempty(row.get('assertions'), 'fidelity condition assertions'):
            path = paths.get(pair.get('path_id'), {})
            require(path.get('kind', 'automation') in ('unit', 'automation', 'visual') and
                    pair.get('assertion_id') in {a['assertion_id'] for a in path.get('expected_assertions', [])} and
                    any(all(pair.get(k) == entry.get(k) for k in ('path_id', 'assertion_id')) for entry in trace['assertions']),
                    'fidelity condition needs item-owned behavioral PATH/ASSERT')


def coverage_review(data, required=False):
    """Only applicable UI/resource dimensions owe a source-backed condition review."""
    for row in data['dimensions']:
        if row['dimension'] not in CONDITION_FACETS or row['status'] != 'applicable': continue
        review = row.get('condition_review')
        require(review is not None or not required, 'UI/Resource condition review required')
        if review is None: continue
        require(isinstance(review, dict) and set(review) == set(CONDITION_FACETS[row['dimension']]), 'condition review facets incomplete')
        applicable = {(item['item_id'], c['condition_id']) for item in row['items']
                      for c in item.get('fidelity_conditions', []) if c['status'] == 'applicable'}
        covered = set()
        for value in review.values():
            require(value.get('reason'), 'condition review source rationale required')
            evidence(value.get('evidence_refs'), 'condition review source evidence')
            refs = value.get('condition_refs')
            require(isinstance(refs, list), 'condition refs must be explicit, empty means source-backed exclusion')
            pairs = {(r.get('item_id'), r.get('condition_id')) for r in refs}
            require(pairs <= applicable, 'condition review references unknown/non-applicable condition')
            covered.update(pairs)
        require(covered == applicable, 'condition review omits applicable conditions')


def registered(s, module_id):
    """The analysis the Ledger holds for a module, or None while the module is only proposed."""
    return (s['modules'].get(module_id) or s.get('module_groups', {}).get(module_id) or {}).get('dimension_analysis_ref')


def allocation(s, module):
    ref = module.get('dimension_analysis_ref')
    if not s.get('dimension_slicing_required') and not ref:
        return {}
    if ref is not None and registered(s, module['module_id']) == ref:
        data, items = load(ref, module['module_id'])
    else:
        data, items = judge(ref, module['module_id'])
        coverage_review(data, s.get('planning_coverage_required', False))
        import api_contract
        api_contract.applicability(data, True)
        if s.get('planning_coverage_required'):
            evidence((data.get('api_review') or {}).get('discovery_refs'), 'API discovery scope required for applicability review')
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
    import api_contract
    parent_data = read_json(check_ref(parent['dimension_analysis_ref']))
    parent_calls, parent_apis = api_contract.read(parent_data, expected)
    api_covered = set()
    coverage = {iid: {'requirements': set(), 'cases': set(), 'conditions': set()} for iid in expected}
    for child in plan['children']:
        items = allocation({**s, 'dimension_slicing_required': True}, child)
        data, _ = load(child['dimension_analysis_ref'], child['module_id'])
        calls, apis = api_contract.read(data, items)
        require(set(apis) <= set(parent_apis) and all(calls[aid] == parent_calls[aid] for aid in apis),
                'child API source outside parent boundary; revise GO inventory first')
        require(not api_covered.intersection(apis), 'API owner duplicated across children')
        api_covered.update(apis)
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
                parent_conditions = {c['condition_id']: c for c in expected[pid].get('fidelity_conditions', [])}
                for condition in item.get('fidelity_conditions', []):
                    original = parent_conditions.get(condition['condition_id'])
                    if original:
                        require(all(condition.get(k) == original.get(k) for k in ('condition', 'status')) and
                                all(ref in condition['evidence_refs'] for ref in original['evidence_refs']),
                                'child changed inherited fidelity condition; revise parent first')
                        coverage[pid]['conditions'].add(condition['condition_id'])
    require(covered == set(expected), 'child dimensions omit parent work (N/A cannot discard inherited work)')
    require(api_covered == set(parent_apis), 'child API inventory omits parent contracts')
    for iid, item in expected.items():
        require({c['condition_id'] for c in item.get('fidelity_conditions', [])} <= coverage[iid]['conditions'],
                'child dimensions omit parent fidelity conditions')
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
    for iid, item in items.items(): fidelity_conditions(item, paths, traces[iid])
    import api_contract
    api_contract.plan(read_json(check_ref(ref)), items, plan)
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
        # The analysis belongs to its task and plan; a scope digest or parent reference, when written, must match them.
        require(analysis.get('scope_sha256', digest(scope)) == digest(scope), 'task dimension analysis must bind current task scope')
        require(analysis.get('parent_ref', plan['dimension_analysis_ref']) == plan['dimension_analysis_ref'], 'task dimension analysis parent mismatch')
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
            # The allocated analysis the plan binds is the evidence of every row; a row cites more only when it has more.
            if row.get('evidence_refs') is not None:
                evidence(row['evidence_refs'], 'task dimension evidence')
            if expected:
                require(row.get('implementation'), 'task dimension needs concrete implementation guidance')


def verify(plan):
    if plan.get('dimension_analysis_ref'):
        load(plan['dimension_analysis_ref'], plan['module_id'])
        for task in plan['tasks']:
            analysis = task.get('dimension_analysis', {})
            require([row.get('dimension') for row in analysis.get('dimensions', [])] == ORDER,
                    'frozen task dimension analysis missing; replan and refreeze')
            require(analysis.get('scope_sha256', digest(task.get('scope'))) == digest(task.get('scope')), 'frozen task scope changed')
            for row in analysis['dimensions']:
                if row.get('evidence_refs') is not None:
                    evidence(row['evidence_refs'], 'frozen task dimension evidence')


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
            import resource_fidelity
            actual = check_ref(trace.get('target_resource_ref'))
            expected = Path(items[iid]['target_resource'].split('#', 1)[0])
            require(expected.is_absolute() and actual.resolve() == expected.resolve(),
                    'resource evidence differs from planned target_resource')
            expected_consumers = [Path(value.split('#', 1)[0]) for value in resource_fidelity.consumers(items[iid])]
            require(all(path.is_absolute() for path in expected_consumers), 'resource consumer must name an absolute production file')
            expected_paths = {path.resolve() for path in expected_consumers}
            refs = consumer_evidence(trace)
            actual_paths = [check_ref(ref).resolve() for ref in refs]
            require(set(actual_paths) == expected_paths and len(actual_paths) == len(expected_paths),
                    'resource evidence differs from planned consumer files')
            # The plan froze how the resource reaches the target; the result is held to it.
            resource_fidelity.verify_exact(items[iid], actual)
            resource_fidelity.verify_wiring(items[iid], actual_paths)
    import parameter_file
    import resource_copy
    analysis = read_json(check_ref(plan['dimension_analysis_ref']))
    resource_copy.verify(analysis, result.get('code_files'))
    parameter_file.verify(analysis, result.get('code_files'))
    import api_contract
    api_contract.implementation(analysis, items, result)


def consumer_evidence(trace):
    """One hash per production file; several symbols may share the same file."""
    refs = trace.get('consumer_refs')
    legacy = trace.get('consumer_ref')
    if refs is None:
        refs = [legacy] if legacy else []
    require(isinstance(refs, list) and refs, 'resource consumer_refs (or legacy consumer_ref) required')
    if legacy:
        require(legacy in refs, 'legacy consumer_ref differs from consumer_refs')
    return refs


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
    analysis_ref = (module.get('plan') or {}).get('dimension_analysis_ref')
    if analysis_ref:
        import parameter_file
        import resource_copy
        resource_copy.verify_files(read_json(check_ref(analysis_ref)))
        parameter_file.verify_files(read_json(check_ref(analysis_ref)))
    for trace in module.get('dimension_evidence', []):
        for ref in trace['evidence_refs']:
            verify(ref)
        if trace.get('target_resource_ref'):
            verify(trace['target_resource_ref'])
        if trace.get('consumer_ref') or trace.get('consumer_refs') is not None:
            for ref in consumer_evidence(trace):
                verify(ref)
