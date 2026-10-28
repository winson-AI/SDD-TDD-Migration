"""What the runs of a project tell about the package they ran on, grouped by the package commit each run was pinned to.

The harvest keeps one row per run in the experience store and writes package-feedback.json and .md beside it, outside the
package: refusals by check, the gaps the Ledger raised by family, the rule debt, how the run was sliced, the model turns per
leaf by role, the largest card, and what the lessons a run was offered did. Every number is counted from the run's journal,
state and reports. It is a report for whoever maintains the package; nothing here edits a rule, a gate or a threshold.
"""
from collections import Counter
import json
from pathlib import Path


def refusals(run_root):
    """Refused requests by operation × role × the rule that refused them, with the attempts each took."""
    from progress_signals import rule
    out = Counter()
    folder = Path(run_root) / 'reports/rejections'
    for path in sorted(folder.glob('*.json')) if folder.is_dir() else ():
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        out['%s × %s × %s' % (record.get('operation'), record.get('actor_role'), record.get('rule') or rule(record.get('reason')))] += record.get('attempts') if type(record.get('attempts')) is int else 1
    return dict(out.most_common())


def gap_families(s):
    """The gaps the Ledger raised on plans, by the rule that owed them: how many were raised and how many are still open."""
    import issues
    out = {}
    for issue in s.get('issues', {}).values():
        if issue['kind'] != 'gap' or issue.get('raised_by') != issues.LEDGER:
            continue
        row = out.setdefault(issues.family('gap', issue['summary']), {'raised': 0, 'open': 0})
        row['raised'] += 1
        row['open'] += any(target not in issue['resolved'] for target in issue['applies_to'])
    return dict(sorted(out.items(), key=lambda item: (-item[1]['raised'], item[0])))


def run_row(s, events, run_root):
    import rule_debt
    import workflow_cost
    leaves = len(s['modules']) or 1
    by_role = Counter((e.get('actor') or {}).get('role') for e in events if workflow_cost.model_turn(e))
    cards = Path(run_root) / 'reports/reading'
    return {'package_sha': s.get('package_sha'), 'run_quality': s.get('quality'), 'refusals': refusals(run_root),
            'gap_families': gap_families(s),
            'rule_debt': [{k: row[k] for k in ('module_id', 'artifact', 'reason')} for row in rule_debt.collect(s)],
            'model_turns': sum(by_role.values()), 'turns_per_leaf': {role: round(n / leaves, 2) for role, n in sorted(by_role.items())},
            'max_card_bytes': max([p.stat().st_size for p in cards.glob('*.md')] if cards.is_dir() else [], default=0),
            'retrospective': retrospective(s)}


def retrospective(s):
    """What the run's retrospective came to; one owed and never submitted is a debt of the run, not a block on it."""
    import experience
    done = s.get('retrospectives') or []
    if done:
        return 'nothing to abstract: ' + done[-1]['nothing_to_abstract'] if done[-1].get('nothing_to_abstract') else 'lessons submitted'
    due = experience.retrospective_due(s)
    return 'owed: %d observations, signals %s' % (due['observations'], ', '.join(due['signals']) or 'none') if due else None


def report(data):
    """The store's runs grouped by package commit; each run's slicing and its lessons' effect come from the store."""
    packages = {}
    for rid, block in sorted(data.get('runs', {}).items()):
        row = block.get('feedback')
        if row:
            packages.setdefault(row.get('package_sha') or 'unpinned', {})[rid] = {**row, 'slicing': block.get('slicing')}
    from experience import effect_counts, gate_key
    named = {gate_key(entry): entry.get('summary') for block in data.get('runs', {}).values() for entry in block.get('entries', [])
             if entry.get('kind') == 'gate-rejection'}
    return {'schema_version': 1, 'packages': packages,
            'lesson_effect': {key: {**row, 'summary': named.get(key)} for key, row in effect_counts(data).items()}}


def markdown(out):
    lines = ['# Package feedback', '', 'Counted from each run; a report, not a change to any rule.', '']
    for sha, runs in out['packages'].items():
        lines += ['## Package %s' % sha[:12], '', '| run | quality | leaves | model turns | turns per leaf by role | max card | refusals | gaps raised / open | rule debt | retrospective |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        refused, gaps = Counter(), Counter()
        for rid, row in runs.items():
            raised = sum(g['raised'] for g in row['gap_families'].values())
            still = sum(g['open'] for g in row['gap_families'].values())
            lines.append('| %s | %s | %s | %s | %s | %s | %s | %s / %s | %s | %s |' % (
                rid, row['run_quality'], (row.get('slicing') or {}).get('leaves', '-'), row['model_turns'],
                ', '.join('%s %s' % item for item in row['turns_per_leaf'].items()) or '-', row['max_card_bytes'],
                sum(row['refusals'].values()), raised, still, len(row['rule_debt']), row.get('retrospective') or '-'))
            refused.update(row['refusals'])
            gaps.update({name: g['raised'] for name, g in row['gap_families'].items()})
        lines += ['', 'Refused checks, attempts over these runs:', ''] + (['- %s: %d' % item for item in refused.most_common(10)] or ['- none'])
        lines += ['', 'Gap families, raised over these runs:', ''] + (['- %s: %d' % item for item in gaps.most_common(10)] or ['- none'])
        lines.append('')
    if out['lesson_effect']:
        lines += ['## Lessons offered', '', '| lesson | runs offered | came back in |', '| --- | --- | --- |']
        lines += ['| %s | %d | %d |' % (row['summary'] or key[:12], row['offered'], row['recurred']) for key, row in sorted(out['lesson_effect'].items())]
    return '\n'.join(lines) + '\n'


def write(directory, data):
    out = report(data)
    from project_context import atomic
    atomic(Path(directory) / 'package-feedback.json', (json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode())
    atomic(Path(directory) / 'package-feedback.md', markdown(out).encode())
    return out
