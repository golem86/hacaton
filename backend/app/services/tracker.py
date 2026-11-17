"""In-memory domain prototype. Authentication and storage belong to integration."""
from copy import deepcopy
from datetime import date

TRANSITIONS = {
    'proposed': {'accepted', 'rejected'},
    'accepted': {'in_progress'},
    'in_progress': {'completed'},
    'completed': {'verified', 'in_progress'},
    'verified': set(), 'rejected': set(),
}


def _date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError('Date must use YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('Date must use YYYY-MM-DD')
    return parsed


def _assessment_id(value: int | str) -> int:
    """Normalize SQLite integer IDs and their decimal JSON/string representation."""
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    raise ValueError('Assessment ID must be a positive decimal integer')


def transition(recommendation: dict, new_status: str, *, actor_id: str,
               human_decision: bool, on_date: str, reason: str,
               owner_id: str | None = None, due_date: str | None = None,
               evidence_refs: tuple[str, ...] = (), next_assessment_id: str | None = None) -> dict:
    """Explicit command from a trusted human session; never called by scoring."""
    if human_decision is not True or not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError('A named human decision is required')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A decision reason is required')
    old_status = recommendation.get('status')
    if new_status not in TRANSITIONS.get(old_status, set()):
        raise ValueError('Invalid status transition')
    today = _date(on_date)
    history = recommendation.get('history', [])
    if history and today < _date(history[-1]['on_date']):
        raise ValueError('History cannot go backwards')
    result = deepcopy(recommendation)
    if new_status == 'accepted':
        if not isinstance(owner_id, str) or not owner_id.strip() or due_date is None:
            raise ValueError('Acceptance requires owner_id and due_date')
        if _date(due_date) < today:
            raise ValueError('Due date precedes acceptance')
        result.update(owner_id=owner_id, due_date=due_date)
    elif owner_id is not None or due_date is not None:
        raise ValueError('Assign owner and deadline when accepting')
    if new_status in {'completed', 'verified'}:
        if (not evidence_refs or isinstance(evidence_refs, str)
                or any(not isinstance(e, str) or not e.strip() for e in evidence_refs)):
            raise ValueError('Completion/verification requires evidence references')
    if new_status == 'verified':
        if not isinstance(next_assessment_id, str):
            raise ValueError('Verification requires a different assessment ID')
        if _assessment_id(next_assessment_id) == _assessment_id(recommendation['assessment_id']):
            raise ValueError('Verification requires a different assessment ID')
        result['next_assessment_id'] = next_assessment_id
    result['status'] = new_status
    result.setdefault('history', []).append({
        'from_status': old_status, 'to_status': new_status, 'actor_id': actor_id,
        'on_date': today.isoformat(), 'reason': reason,
        'owner_id': result.get('owner_id'), 'due_date': result.get('due_date'),
        'evidence_refs': list(evidence_refs), 'next_assessment_id': next_assessment_id,
    })
    return result


def is_overdue(recommendation: dict, *, as_of: str) -> bool:
    """A derived flag, not a status; exact deadline day is not overdue."""
    today = _date(as_of)
    return (recommendation.get('status') in {'accepted', 'in_progress'}
            and bool(recommendation.get('due_date'))
            and _date(recommendation['due_date']) < today)
