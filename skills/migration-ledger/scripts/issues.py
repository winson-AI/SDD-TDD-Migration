"""Problems are recorded and work goes on.

An issue is addressed to the modules it concerns and stays open for each of them until that module cites what settled
it. Recording or settling one moves nobody's revision, so it never makes a request somebody else is about to submit
stale. Only an issue raised as blocking holds anything, and only the freeze of a module it is addressed to: that is how
a review says a plan is certain to fail. A standing rule is followed, not settled."""
from contracts import check_ref, require

import hashlib

OPS = {'issue', 'issue-resolve'}
KINDS = ('defect', 'fact', 'gap', 'need', 'decision', 'standing')
LEDGER = {'role': 'ledger', 'instance_id': 'ledger'}


def handle(s, req, actor):
    p = req.get('payload', {})
    issues = s.setdefault('issues', {})
    if req['operation'] == 'issue':
        iid, targets = p.get('issue_id'), p.get('applies_to')
        require(isinstance(iid, str) and iid.strip() and iid not in issues, 'issue_id must be new')
        require(p.get('kind') in KINDS, 'issue kind is one of ' + ', '.join(KINDS))
        require(isinstance(p.get('summary'), str) and p['summary'].strip(), 'issue summary required')
        require(isinstance(targets, list) and targets and set(targets) <= set(s['modules']) | set(s.get('module_groups', {})),
                'issue applies_to names the registered modules it concerns')
        require(not (p.get('blocks') and p['kind'] == 'standing'), 'a standing rule is followed, not settled; it cannot block')
        for ref in p.get('evidence_refs') or []:
            check_ref(ref)
        issues[iid] = {'kind': p['kind'], 'summary': p['summary'].strip(), 'applies_to': sorted(set(targets)),
                       'blocks': bool(p.get('blocks')), 'evidence_refs': list(p.get('evidence_refs') or []),
                       'raised_by': actor, 'resolved': {}}
        return
    issue, mid = issues.get(p.get('issue_id')), p.get('module_id')
    require(issue and issue['kind'] != 'standing', 'issue-resolve names a recorded issue that is not a standing rule')
    require(issue['raised_by'] != LEDGER, 'a gap the Ledger recorded is settled by a plan that no longer owes it')
    require(mid in issue['applies_to'] and mid not in issue['resolved'], 'issue is not open for this module')
    check_ref(p.get('evidence_ref'))
    issue['resolved'][mid] = {'evidence_ref': p['evidence_ref'], 'by': actor}


def of_module(s, mid=None):
    """(open, standing) for one module, or for every module when none is named: what is still owed, and what is always followed."""
    rows = [{'issue_id': iid, **{key: issue[key] for key in ('kind', 'summary', 'blocks', 'evidence_refs')},
             'open_for': [target for target in issue['applies_to'] if target not in issue['resolved']]}
            for iid, issue in sorted(s.get('issues', {}).items()) if mid is None or mid in issue['applies_to']]
    standing = [row for row in rows if row['kind'] == 'standing']
    return [row for row in rows if row['kind'] != 'standing' and (mid in row['open_for'] if mid else row['open_for'])], standing


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
