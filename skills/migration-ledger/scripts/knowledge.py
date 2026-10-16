"""Knowledge a run may stand on: the project's own documents, and what a person supplied when the run asked.

A role that needs a fact nobody's source, target or document holds records a `knowledge-need` issue; a person answers
it with a decision of kind `knowledge`, which the Ledger writes as a document of the run, hands to the leaves the
question concerned, and accepts as the only way that need is settled."""
from datetime import datetime, timezone
from pathlib import Path

from contracts import check_ref, digest, file_ref, nonempty, read_json, require

KIND = 'knowledge-need'
FOLDER = 'artifacts/knowledge'


def snapshot(s):
    ref = s.get('project_context_ref')
    if not ref:
        return {}
    import project_context
    try:
        return project_context.verify_snapshot(ref)
    except (ValueError, OSError, KeyError, TypeError):
        return {}


def documents(s):
    """The project's knowledge documents as the run holds them: [{path, sha256}]."""
    return [ref for ref in (snapshot(s).get('source_refs') or {}).get('knowledge_paths') or [] if isinstance(ref, dict) and ref.get('path')]


def answers(s):
    """The knowledge decisions of the run: [{decision_id, issue_id, applies_to, ref}]."""
    return [{'decision_id': did, 'issue_id': d.get('question_id'), 'applies_to': list((s.get('issues') or {}).get(d.get('question_id'), {}).get('applies_to') or []),
             'ref': d['knowledge_ref']} for did, d in sorted((s.get('decisions') or {}).items()) if d.get('kind') == 'knowledge' and d.get('knowledge_ref')]


def of_module(s, module):
    return [row for row in answers(s) if module['module_id'] in row['applies_to']]


def settles(s, issue, ref):
    """A knowledge need is settled only by a knowledge decision's document or one of the project's knowledge documents."""
    if issue.get('kind') != KIND:
        return True
    path = str(Path(ref['path']).resolve())
    allowed = {str(Path(d['path']).resolve()) for d in documents(s)} | {str(Path(a['ref']['path']).resolve()) for a in answers(s)}
    return path in allowed


def subject(issue_id, issue):
    """What a person answers: the question as recorded."""
    return digest({'issue_id': issue_id, 'summary': issue['summary'], 'applies_to': issue['applies_to']})


def decision(s, p, root, actor):
    """Record a person's answer to a knowledge need: write it as a document of the run and settle the need for every
    module it concerned. Sources are required: a fact from outside the run names where it came from."""
    issue = (s.get('issues') or {}).get(p.get('question_id'))
    require(issue and issue.get('kind') == KIND, 'a knowledge decision answers a recorded knowledge-need issue (question_id)')
    require(p.get('subject_sha256') == subject(p['question_id'], issue), 'knowledge decision subject must hash the question as recorded')
    rows = nonempty(p.get('answers'), 'knowledge answers')
    require(all(isinstance(row, str) and row.strip() for row in rows), 'knowledge answers are statements')
    sources = nonempty(p.get('sources'), 'knowledge sources (documents, URLs or named authorities)')
    require(all(isinstance(src, str) and src.strip() for src in sources), 'knowledge sources are named')
    require(root is not None, 'a knowledge decision needs the run root to write its document')
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (p['decision_id'] + '.md')
    require(not path.exists(), 'knowledge document already written for this decision')
    text = ['# ' + p['decision_id'] + ' · ' + p['question_id'], '', '问题：' + issue['summary'], '', '适用模块：' + ', '.join(issue['applies_to']), '',
            '## 答复', '', *['- ' + row.strip() for row in rows], '', '## 来源', '', *['- ' + src.strip() for src in sources], '',
            '记录：' + json_actor(actor) + ' · ' + datetime.now(timezone.utc).isoformat(), '']
    path.write_text('\n'.join(text))
    ref = file_ref(path)
    for mid in issue['applies_to']:
        issue['resolved'][mid] = {'by': actor, 'decision_id': p['decision_id'], 'evidence_ref': ref}
    return ref


def json_actor(actor):
    return '%s/%s' % (actor.get('role'), actor.get('instance_id')) if isinstance(actor, dict) else str(actor)


def search(s, query, limit=20):
    """Lines of the project's knowledge documents that mention the query, document by document."""
    needle = query.lower()
    matches = []
    for ref in documents(s):
        try:
            lines = check_ref(ref).read_text(errors='replace').splitlines()
        except (ValueError, OSError):
            continue
        hits = [{'line': n, 'text': line.strip()[:200]} for n, line in enumerate(lines, 1) if needle in line.lower()]
        if hits:
            matches.append({'ref': ref, 'hits': hits[:limit], 'count': len(hits)})
    return matches
