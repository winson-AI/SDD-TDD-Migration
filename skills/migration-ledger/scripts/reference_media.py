"""What the user showed of the legacy application: screenshots and recordings, each bound to the cases it shows.

They enter the run with the project context, copied and hash-bound like its documents, and reach the leaf that accepts
those cases. A screenshot stands as the visual baseline of a screen the legacy cannot preview (`visual_mode:
user-reference`); a recording is the interaction a functional PATH follows. A PATH cites a medium by `baseline_ref`
(a visual PATH) or `reference_media_ids`; a case the user showed that no PATH cites is owed by the leaf.

A medium of role `target-expectation` (a design, a target screenshot) replaces the legacy baseline as the alignment
target of the screens it covers, whether or not the legacy can be previewed; behaviour is still the legacy's. The design
cites it, and the report discloses that those screens were aligned to it and not compared with the legacy screen."""
from pathlib import Path

from contracts import check_ref, nonempty, owed, read_json, require

KINDS = ('screenshot', 'video')
ROLES = ('legacy-baseline', 'target-expectation')
FIELDS = {'media_id', 'kind', 'path', 'role', 'screen', 'case_ids', 'note'}
MODE = 'user-reference'


def configured(value):
    """The project's reference_media as configured: validated, paths resolved, the default role written."""
    require(isinstance(value, list), 'reference_media must be a list')
    rows, seen = [], set()
    for row in value:
        require(isinstance(row, dict) and set(row) <= FIELDS, 'reference_media rows take media_id, kind, path, role, screen, case_ids and note')
        mid = row.get('media_id')
        require(isinstance(mid, str) and mid.strip() and mid not in seen, 'reference_media needs a unique media_id')
        seen.add(mid)
        require(row.get('kind') in KINDS, 'reference_media kind is screenshot or video')
        require(row.get('role', ROLES[0]) in ROLES, 'reference_media role is one of ' + ', '.join(ROLES))
        require(isinstance(row.get('path'), str) and Path(row['path']).is_absolute(), 'reference_media path must be absolute')
        cases = row.get('case_ids')
        require(isinstance(cases, list) and cases and all(isinstance(c, str) and c for c in cases), 'reference_media names the case_ids it shows')
        require(all(isinstance(row.get(key, ''), str) for key in ('screen', 'note')), 'reference_media screen and note are text')
        rows.append({**row, 'path': str(Path(row['path']).resolve()), 'role': row.get('role', ROLES[0]), 'case_ids': list(dict.fromkeys(cases))})
    return rows


def rows(s):
    """The run's reference media as its context snapshot holds them: [{media_id, kind, role, screen, case_ids, note, ref}]."""
    ref = s.get('project_context_ref')
    if not ref:
        return []
    try:
        snapshot = read_json(check_ref(ref))
    except (ValueError, OSError, TypeError):
        return []
    return [row for row in (snapshot.get('source_refs') or {}).get('reference_media') or []
            if isinstance(row, dict) and isinstance(row.get('ref'), dict)]


def bound(s, case_ids):
    held = set(case_ids or [])
    return [row for row in rows(s) if held.intersection(row['case_ids'])]


def of_module(s, module):
    return bound(s, module.get('case_ids') or [])


def shots(media, role=None):
    """{sha256: row} of the screenshots among `media` (of one role when given): the bytes a visual baseline may be."""
    return {row['ref']['sha256']: row for row in media if row['kind'] == 'screenshot' and role in (None, row['role'])}


def expectation(s, item):
    """The target expectation screenshots of an item's cases: where they exist, they are the baseline."""
    return shots(bound(s, item.get('case_ids') or []), 'target-expectation')


def cites(path, row):
    """Whether a PATH cites this medium: as its visual baseline (same bytes) or by id."""
    ref = path.get('baseline_ref')
    return row['media_id'] in (path.get('reference_media_ids') or []) or (isinstance(ref, dict) and ref.get('sha256') == row['ref']['sha256'])


def evidence_gate(s, item, evidence):
    """A UI item against the media of its cases. A target expectation replaces the legacy baseline: the item aligns to it.
    Otherwise user-reference cites the user's legacy screenshots of those cases and every case shown gets one; a screen
    the user showed is not left source-only."""
    media = bound(s, item.get('case_ids') or [])
    expected = shots(media, 'target-expectation')
    pictures = expected or shots(media, 'legacy-baseline')
    mode = evidence.get('visual_mode')
    what = 'target expectation screenshot' if expected else 'reference screenshot'
    if expected:  # completeness: the first version may go on, the gap is owed and reported
        owed(mode == MODE, 'the user gave a target expectation for this screen: align to it (visual_mode user-reference citing '
             + ', '.join(sorted(row['media_id'] for row in expected.values())) + ') in ' + item['item_id'])
    if mode == MODE:
        cited = []
        for ref in nonempty(evidence.get('baseline_refs'), 'user reference screenshots for ' + item['item_id']):
            check_ref(ref)
            require(ref.get('sha256') in pictures, 'user-reference baselines are the ' + what + 's of the cases of ' + item['item_id'])
            cited.append(pictures[ref['sha256']])
        shown = set(item.get('case_ids') or []).intersection(cid for row in pictures.values() for cid in row['case_ids'])
        for cid in sorted(shown):
            owed(any(cid in row['case_ids'] for row in cited), 'the user showed ' + cid + ': cite its ' + what + ' in ' + item['item_id'])
    elif mode == 'source-only':
        owed(not pictures, 'the user showed this screen: cite the reference screenshots (visual_mode user-reference) instead of source-only for ' + item['item_id'])


def plan_gate(s, m, plan):
    """What a plan cites exists and shows the case: reference_media_ids name the run's media of the PATH's case, and a visual
    baseline that is a user screenshot is one of that case."""
    media = rows(s)
    by_id, pictures = {row['media_id']: row for row in media}, shots(media)
    for path in plan.get('paths', []):
        ids = path.get('reference_media_ids')
        if ids is not None:
            require(isinstance(ids, list) and ids and len(set(ids)) == len(ids) and all(i in by_id for i in ids),
                    'reference_media_ids name the run reference media, without repeats: ' + path['path_id'])
            for i in ids:
                require(path.get('case_id') in by_id[i]['case_ids'], f"reference media {i} does not show case {path.get('case_id')} of {path['path_id']}")
        ref = path.get('baseline_ref')
        if path.get('kind') == 'visual' and isinstance(ref, dict) and ref.get('sha256') in pictures:
            require(path.get('case_id') in pictures[ref['sha256']]['case_ids'], 'the reference screenshot cited by ' + path['path_id'] + ' does not show its case')


def freeze(s, m):
    """What the user showed is aligned where it is shown: a case the leaf accepts, an applicable UI item carries and a medium
    shows has a PATH citing that medium, unless the case is a declared device gap."""
    import user_paths
    plan = m.get('plan') or {}
    media = of_module(s, m)
    if not media or not plan.get('dimension_analysis_ref'):
        return
    visible = user_paths.visible_cases(m, read_json(check_ref(plan['dimension_analysis_ref']))) - set(user_paths.gaps(plan))
    replaced = {cid for row in shots(media, 'target-expectation').values() for cid in row['case_ids']}  # the expectation is the baseline there
    designs = [d for d in plan.get('definitions') or [] if d.get('kind') == 'design']
    text = None
    for row in media:
        shown = sorted(visible.intersection(row['case_ids']) - (replaced if row['role'] == 'legacy-baseline' and row['kind'] == 'screenshot' else set()))
        if shown and row['role'] == 'target-expectation':  # what the target should look like shapes the design before it is a baseline
            text = ''.join(check_ref(d).read_text() for d in designs) if text is None else text
            owed(row['media_id'] in text, 'the target expectation ' + row['media_id'] + ' shapes the design: cite it in the design definition')
        owed(not shown or any(cites(path, row) for path in plan.get('paths', [])),
             f"the user showed {', '.join(shown)} in {row['media_id']}: a PATH cites it (a visual baseline_ref or reference_media_ids), or the case is a declared device gap")


def report(s):
    """Per medium: what it shows, which leaves hold those cases, which PATHs cite it and, for an expectation, the legacy
    screenshots it replaces."""
    media = rows(s); out = []
    for row in media:
        held = {mid: m for mid, m in s['modules'].items() if set(row['case_ids']).intersection(m.get('case_ids') or [])}
        cited = sorted(f"{mid}:{path['path_id']}" for mid, m in held.items() for path in (m.get('plan') or {}).get('paths', []) if cites(path, row))
        overrides = sorted(o['media_id'] for o in media if o['role'] == 'legacy-baseline' and o['kind'] == 'screenshot'
                           and set(o['case_ids']).intersection(row['case_ids'])) if row['role'] == 'target-expectation' else []
        out.append({'media_id': row['media_id'], 'kind': row['kind'], 'role': row['role'], 'screen': row.get('screen') or '', 'case_ids': list(row['case_ids']),
                    'modules': sorted(held), 'cited_by': cited, 'status': 'cited' if cited else 'uncited', 'overrides': overrides, 'ref': row['ref']})
    return out


def disclosures(s):
    """What the report discloses of a screen aligned to a target expectation: it was not compared with the legacy screen."""
    return [{'module_id': mid, 'item_id': None, 'kind': 'target-expectation', 'case_ids': list(row['case_ids']),
             'reason': f"CASE {'、'.join(row['case_ids'])} 按用户目标预期 {row['media_id']} 对齐，取代存量基线"
                       + (f"（存量参考 {'、'.join(row['overrides'])}）" if row['overrides'] else '') + '，不证明与存量界面一致',
             'evidence_refs': [row['ref']]}
            for row in report(s) if row['role'] == 'target-expectation' for mid in row['modules']]
