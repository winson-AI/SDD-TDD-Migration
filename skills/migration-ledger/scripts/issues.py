"""Problems are recorded and work goes on.

An issue is addressed to the modules it concerns and stays open for each of them until that module cites what settled
it. Recording or settling one moves nobody's revision, so it never makes a request somebody else is about to submit
stale. Only an issue raised as blocking holds anything, and only the freeze of a module it is addressed to: that is how
a review says a plan is certain to fail. A standing rule is followed, not settled."""
from contracts import check_ref, digest, require

import hashlib

OPS = {'issue', 'issue-resolve'}
KINDS = ('defect', 'fact', 'gap', 'need', 'decision', 'standing', 'debt', 'knowledge-need')  # a debt is a fact about the code, owed to nobody; a knowledge-need is answered by a person
LEDGER = {'role': 'ledger', 'instance_id': 'ledger'}
STEP_CHARS = 200     # what a step view shows of each line
STEP_ROWS = 10       # how many open issues a step lists: the blocking ones first, then the newest


def handle(s, req, actor, sequence=None):
    """One request records every issue it carries, or settles every resolution it carries: a role that has several to
    say says them in one event, and nothing is recorded unless all of them stand."""
    p = req.get('payload', {})
    issues = s.setdefault('issues', {})
    if req['operation'] == 'issue':
        entries = p['issues'] if isinstance(p.get('issues'), list) else [p]
        require(entries, 'an issue request records at least one issue')
        judged = {}
        for e in entries:
            iid, targets = e.get('issue_id'), e.get('applies_to')
            require(isinstance(iid, str) and iid.strip() and iid not in issues and iid not in judged, 'issue_id must be new')
            require(e.get('kind') in KINDS, 'issue kind is one of ' + ', '.join(KINDS))
            require(isinstance(e.get('summary'), str) and e['summary'].strip(), 'issue summary required')
            require(isinstance(targets, list) and targets and set(targets) <= set(s['modules']) | set(s.get('module_groups', {})),
                    'issue applies_to names the registered modules it concerns')
            require(not (e.get('blocks') and e['kind'] in ('standing', 'fact', 'debt')), 'a standing rule is followed and a fact or debt is recorded, not settled; it cannot block')
            for ref in e.get('evidence_refs') or []:
                check_ref(ref)
            judged[iid] = {'kind': e['kind'], 'summary': e['summary'].strip(), 'applies_to': sorted(set(targets)),
                           'blocks': bool(e.get('blocks')), 'evidence_refs': list(e.get('evidence_refs') or []),
                           'raised_by': actor, 'sequence': sequence,
                           # a fact is kept for the trace and owed to nobody: it is settled as it is recorded
                           'resolved': {t: {'by': actor, 'recorded': True} for t in targets} if e['kind'] in ('fact', 'debt') else {}}
        issues.update(judged)
        return
    entries = p['resolutions'] if isinstance(p.get('resolutions'), list) else [p]
    require(entries, 'an issue-resolve request settles at least one issue')
    pending = []
    for e in entries:
        iid, mid, ref = e.get('issue_id'), e.get('module_id', p.get('module_id')), e.get('evidence_ref', p.get('evidence_ref'))
        issue = issues.get(iid)
        require(issue and issue['kind'] != 'standing', 'issue-resolve names a recorded issue that is not a standing rule')
        require(issue['raised_by'] != LEDGER, 'a gap the Ledger recorded is settled by a plan that no longer owes it')
        require(mid in issue['applies_to'] and mid not in issue['resolved'] and (iid, mid) not in [(a, b) for a, b, _ in pending],
                'issue is not open for this module')
        check_ref(ref)
        import knowledge
        require(knowledge.settles(s, issue, ref), 'a knowledge need is settled by a knowledge decision (kind=knowledge) or one of the project\'s knowledge documents')
        pending.append((iid, mid, ref))
    for iid, mid, ref in pending:
        issues[iid]['resolved'][mid] = {'evidence_ref': ref, 'by': actor}


def cite(s, mid, ids, evidence_ref, actor):
    """What an operation settles by naming it: the issues it lists, open for this module, are resolved with the
    operation's own artifact as evidence - no separate resolution, and nothing is resubmitted to bind them."""
    if not ids:
        return
    require(isinstance(ids, list) and ids and all(isinstance(i, str) for i in ids), 'resolves names issue ids')
    issues = s.get('issues') or {}
    for iid in ids:
        issue = issues.get(iid)
        require(issue and issue['kind'] != 'standing' and issue['raised_by'] != LEDGER,
                'resolves names a recorded issue that is neither a standing rule nor a gap the Ledger owes: ' + str(iid))
        require(mid in issue['applies_to'] and mid not in issue['resolved'], 'issue is not open for this module: ' + iid)
        issue['resolved'][mid] = {'evidence_ref': evidence_ref, 'by': actor}


def record(s, iid, kind, summary, applies_to, raised_by, evidence_refs=(), **extra):
    """An issue the Ledger records itself, once: what an audit sends back to be revised."""
    s.setdefault('issues', {}).setdefault(iid, {'kind': kind, 'summary': summary, 'applies_to': sorted(set(applies_to)), 'blocks': False,
                                                'evidence_refs': list(evidence_refs), 'raised_by': raised_by, 'resolved': {}, **extra})


def of_module(s, mid=None):
    """(open, standing) for one module, or for every module when none is named: what is still owed, and what is always followed."""
    rows = [{'issue_id': iid, **{key: issue[key] for key in ('kind', 'summary', 'blocks', 'evidence_refs')}, 'sequence': issue.get('sequence'),
             'open_for': [target for target in issue['applies_to'] if target not in issue['resolved']]}
            for iid, issue in sorted(s.get('issues', {}).items()) if mid is None or mid in issue['applies_to']]
    standing = [row for row in rows if row['kind'] == 'standing']
    return [row for row in rows if row['kind'] != 'standing' and (mid in row['open_for'] if mid else row['open_for'])], standing


def listed(rows):
    """What a step shows of a module's open issues: the blocking ones first, then the newest, at most STEP_ROWS of them,
    and how many there are in all."""
    ordered = sorted(rows, key=lambda row: (not row['blocks'], -(row.get('sequence') or 0)))
    return [brief(row) for row in ordered[:STEP_ROWS]], len(rows)


def standing_view(rows, since=None):
    """Standing rules ride a step in full when the reader may not have them: at the first read, or when one was recorded
    after the sequence the reader has seen. Otherwise the step names their number and digest."""
    if since is None or any((row.get('sequence') or 0) > since for row in rows):
        return [brief(row) for row in rows]
    return {'count': len(rows), 'sha256': digest(sorted(row['issue_id'] for row in rows))}


def brief(row, limit=STEP_CHARS):
    """A row as a step view shows it: the head of the line; the state keeps the whole line."""
    text = row['summary']
    return row if len(text) <= limit else {**row, 'summary': text[:limit - 1] + '…'}


def owe(s, mid, gaps, renewed=False):
    """Record what a leaf's plan owes to fidelity. Each gap is an issue of that leaf under an id made from its text; a
    newly judged plan (`renewed`) settles the ones it no longer owes, and a gap seen again is owed again."""
    issues = s.setdefault('issues', {})
    seen = {'OWED-%s-%s' % (mid, hashlib.sha256(text.encode()).hexdigest()[:8]): text for text in gaps}
    for iid, text in seen.items():
        issue = issues.setdefault(iid, {'kind': 'gap', 'summary': text, 'applies_to': [mid], 'blocks': False,
                                        'evidence_refs': [], 'raised_by': LEDGER, 'resolved': {}})
        issue['resolved'].pop(mid, None)
    if renewed:
        for iid, issue in issues.items():
            if issue['raised_by'] == LEDGER and issue['applies_to'] == [mid] and iid not in seen and mid not in issue['resolved']:
                issue['resolved'][mid] = {'by': LEDGER, 'plan_hash': s['modules'][mid]['plan_hash']}
    if not issues:
        s.pop('issues')


def settled(s, mid):
    """A module is done when nothing recorded for it is still open."""
    owed = [row['issue_id'] for row in of_module(s, mid)[0]]
    require(not owed, 'open issues of this module: ' + ', '.join(owed[:8]) + '; settle each (issue-resolve citing what '
            'answers it; a gap the Ledger recorded, by a plan that no longer owes it) before completion')


def hold(s, mid):
    """A blocking issue open for a module holds its freeze, and nothing else."""
    blocking = [row['issue_id'] for row in of_module(s, mid)[0] if row['blocks']]
    require(not blocking, 'blocking issue open for this module: ' + ', '.join(blocking)
            + '; settle it with issue-resolve citing the plan that answers it')
