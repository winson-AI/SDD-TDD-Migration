"""Foundation dependency-resolution gate absorbed from the lean knowledge discipline.

Before architecture or catalog edits, every target-sensitive dependency is resolved to an exact
version and only the API subclosure this slice needs. Demo-source evidence is a candidate
configuration, never compile or device proof. Off by default; when dependency_resolution_required is
enabled at init/prepare, freezing requires a validated resolution artifact produced by the mapped
lean `foundation_gate resolve`.
"""
from pathlib import Path
from contracts import Rejected, check_ref, read_json, require


def validate_resolution(ref, strict=False, target_root=None, check_target=False):
    data = read_json(check_ref(ref))
    require(isinstance(data, dict), 'dependency resolution must be an object')
    for evidence in data.get('knowledge_refs', []):
        check_ref(evidence)
    require(data.get('schema_version') == 1, 'dependency resolution schema_version 1 required')
    requirements = data.get('requirements')
    require(isinstance(requirements, list), 'resolved requirements must be a list')
    status = data.get('status')
    if strict or data.get('producer') == 'lean-knowledge':
        # A caller-supplied producer string is not proof of catalog resolution.
        # Recompute the selected entries from the exact hash-bound bundled catalog.
        from lean_tools import foundation_gate
        catalog, entries = foundation_gate._foundation_catalog()
        refs = [r for r in data.get('knowledge_refs', []) if r.get('path') == str(catalog)]
        require(data.get('catalog') == str(catalog) and len(refs) == 1,
                'managed resolution must bind the bundled Foundation catalog')
        check_ref(refs[0])
        require(data.get('target_root') and isinstance(data.get('target_matrix'), dict),
                'managed resolution must bind target_root and target_matrix')
        if target_root:
            require(Path(data['target_root']).resolve() == Path(target_root).resolve(),
                    'dependency resolution belongs to another target')
        if check_target:
            require(data['target_matrix'].get('harmony') is foundation_gate._target_has_ohos(Path(target_root)),
                    'dependency resolution target matrix differs from actual target')
        for item in requirements:
            require(isinstance(item, dict) and isinstance(item.get('query'), str), 'invalid managed requirement')
            try:
                resolved = foundation_gate._compact(foundation_gate._exact_requirement(entries, item['query']), item['query'])
            except RuntimeError as exc:
                raise Rejected(str(exc)) from exc
            require(all(item.get(key) == value for key, value in resolved.items()),
                    'managed resolution differs from its Foundation catalog: ' + item['query'])
        if requirements:
            require(status == 'passed' and (data.get('target_matrix') or {}).get('harmony') is True,
                    'managed Foundation requirements need a Harmony target')
    if not requirements:
        matrix = data.get('target_matrix') or {}
        require(status in ('not_required_no_new_dependencies', 'not_required_non_harmony_target'),
                'empty dependencies require an explicit not-required result')
        require(matrix.get('harmony') is (status == 'not_required_no_new_dependencies'),
                'not-required result disagrees with target matrix')
        return data
    require(status in (None, 'passed'), 'dependency resolution did not pass')
    for item in requirements:
        require(isinstance(item, dict), 'resolution requirement must be an object')
        version = item.get('resolved_version', item.get('version'))
        require(isinstance(item.get('query'), str) and item['query'].strip() and
                isinstance(version, str) and version.strip(), 'each requirement needs query and resolved_version/version')
        require(not (item.get('version') and item.get('resolved_version')) or
                item['version'] == item['resolved_version'], 'conflicting dependency versions')
        require(item.get('subclosure') is None or isinstance(item['subclosure'], list),
                'subclosure must list only the APIs this slice needs')
        require(item.get('evidence') != 'demo-source' or item.get('candidate_only') is True,
                'demo-source evidence is a candidate configuration, not compile/device proof: ' + str(item['query']))
    return data


def freeze_gate(s, m):
    if not s.get('dependency_resolution_required'):
        return
    ref = (m.get('plan') or {}).get('dependency_resolution_ref')
    require(ref, 'dependency_resolution_required: plan must bind a foundation resolution artifact')
    data = validate_resolution(ref, strict=s.get('evidence_contract_version', 1) >= 2,
                               target_root=s.get('target_root'), check_target=bool(s.get('target_root')))
    if data.get('target_root'):
        require(data['target_root'] == s['target_root'], 'dependency resolution belongs to another target')
