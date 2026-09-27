"""Foundation dependency-resolution gate absorbed from the lean knowledge discipline.

Before architecture or catalog edits, every target-sensitive dependency is resolved to an exact
version and only the API subclosure this slice needs. Demo-source evidence is a candidate
configuration, never compile or device proof. Off by default; when dependency_resolution_required is
enabled at init/prepare, freezing requires a validated resolution artifact produced by the mapped
lean `foundation_gate resolve`.
"""
from contracts import check_ref, nonempty, read_json, require


def validate_resolution(ref):
    data = read_json(check_ref(ref))
    require(data.get('schema_version') == 1, 'dependency resolution schema_version 1 required')
    for item in nonempty(data.get('requirements'), 'resolved requirements'):
        require(isinstance(item, dict), 'resolution requirement must be an object')
        require(item.get('query') and item.get('resolved_version'),
                'each requirement needs query and resolved_version')
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
    validate_resolution(ref)
