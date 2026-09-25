"""Advisory two-tier model routing. Weak-reasoning steps (running commands, capturing
and comparing observations) use the low-cost tier; design/root-cause/verdict need the
strong tier. The host resolves tier -> model (from project-context runtime.model_routing)
and dispatches; the controller only advises the tier, forbids downgrading strong-only
steps, and persists the model the host reports so tasks can be traced afterwards.
"""
from contracts import require

TIERS = ('low_cost', 'strong')

# Weak reasoning: execution and mechanical acceptance. Deterministic assertion compare
# is done by execute_test.py (no model); ambiguous results escalate via Diagnostician.
LOW_COST_ROLES = {'test-runner'}
LOW_COST_OPERATIONS = {'accept', 'submit', 'dependency-ready', 'audit-retest', 'automation-resume'}
# Strong reasoning that must never run on the low-cost model.
STRONG_ONLY_ROLES = {'spec-designer', 'diagnostician', 'auditor'}
STRONG_ONLY_OPERATIONS = {'plan', 'freeze', 'diagnose', 'audit-plan', 'audit-verdict', 'audit', 'problem-audit'}


def strong_only(role=None, operation=None, worker_role=None):
    return (worker_role or role) in STRONG_ONLY_ROLES or operation in STRONG_ONLY_OPERATIONS


def advise(role=None, operation=None, worker_role=None, escalate=False):
    """Recommended tier for a cursor step. Default is strong; only clearly weak steps drop."""
    if escalate or strong_only(role, operation, worker_role):
        return 'strong'
    if (worker_role or role) in LOW_COST_ROLES or operation in LOW_COST_OPERATIONS:
        return 'low_cost'
    return 'strong'


def enforce(role=None, operation=None, tier=None, worker_role=None):
    require(tier in TIERS, 'invalid model tier')
    require(not (strong_only(role, operation, worker_role) and tier == 'low_cost'),
            'strong-reasoning step cannot run on the low-cost model')


def record(payload, role=None, operation=None, worker_role=None):
    """Presence-triggered: return the host-reported model usage to persist, or None."""
    model = payload.get('model')
    tier = payload.get('model_tier')
    if model is None and tier is None:
        return None
    require(isinstance(model, str) and model, 'reported model id required with model routing')
    tier = tier or advise(role, operation, worker_role)
    enforce(role, operation, tier, worker_role)
    return {'model': model, 'model_tier': tier}


def validate_config(routing):
    require(isinstance(routing, dict), 'model_routing must be an object')
    for tier in TIERS:
        spec = routing.get(tier, {})
        require(isinstance(spec, dict) and isinstance(spec.get('model'), str) and spec['model'], tier + ' model id required')
    require(routing.get('default_tier', 'strong') in TIERS, 'invalid default_tier')
    overrides = routing.get('overrides', {})
    require(isinstance(overrides, dict), 'model_routing overrides must be an object')
    for key, tier in overrides.items():
        require(tier in TIERS, 'invalid override tier for ' + str(key))
        require(not (strong_only(key, key) and tier == 'low_cost'), 'cannot downgrade strong-only step: ' + str(key))
