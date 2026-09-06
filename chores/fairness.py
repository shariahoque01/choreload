"""Fairness calculation (#22): each member's rolling 7-day workload,
adjusted by their stated availability.

`calculate_workload` is a pure function — reads only, no writes, no
other side effects (see the module docstring's "no side effects"
constraint).

Formula (locked in by the issue):

    fairness_pct = member_rolling_minutes / (
        household_total_rolling_minutes
        * (member_available_hours / sum_of_all_members_available_hours)
    )

Only `ChoreOccurrence.completed_by` and `Contribution.member` count
towards workload — never `claimed_by`. Unclaimed and overdue
occurrences are excluded entirely (only DONE occurrences, filtered by
`completed_at`, count).

Divide-by-zero guard: a member with `available_hours` summing to 0 is
excluded from the denominator's sum, and their own `fairness_pct` is
undefined (None) rather than a divide error. If the household did no
work at all in the window, `fairness_pct` is also None for everyone
(0/0 is equally undefined).
"""

import datetime

from households.models import Membership

from .models import ChoreOccurrence, Contribution

ROLLING_WINDOW_DAYS = 7


def _available_hours(membership):
    """Total weekly available hours for a member — the sum of whatever
    per-day hours are captured in `available_hours` (#37, deferred; this
    task only needs to read whatever is there, defaulting to 0)."""
    return sum(membership.available_hours.values()) if membership.available_hours else 0

def _rolling_minutes(household, member, window_start, as_of):
    """Minutes `member` is credited with in [window_start, as_of],
    counting only DONE occurrences via completed_by/Contribution —
    never claimed_by, never unclaimed/overdue occurrences."""
    completed_minutes = sum(
        occurrence.chore.estimated_minutes
        for occurrence in ChoreOccurrence.objects.filter(
            chore__household=household,
            completed_by=member,
            status=ChoreOccurrence.Status.DONE,
            completed_at__date__gte=window_start,
            completed_at__date__lte=as_of,
        ).select_related('chore')
    )
    contribution_minutes = sum(
        contribution.minutes_spent
        for contribution in Contribution.objects.filter(
            member=member,
            occurrence__chore__household=household,
            occurrence__status=ChoreOccurrence.Status.DONE,
            occurrence__completed_at__date__gte=window_start,
            occurrence__completed_at__date__lte=as_of,
        )
    )
    return completed_minutes + contribution_minutes


def calculate_workload(household, member, as_of):
    """Returns a dict: rolling_minutes, household_total_minutes,
    available_hours, fairness_pct (None when undefined)."""
    window_start = as_of - datetime.timedelta(days=ROLLING_WINDOW_DAYS)

    active_memberships = list(Membership.objects.filter(household=household, is_active=True))
    member_minutes = _rolling_minutes(household, member, window_start, as_of)
    household_total_minutes = sum(
        _rolling_minutes(household, m, window_start, as_of) for m in active_memberships
    )

    member_hours = _available_hours(member)
    total_available_hours = sum(
        _available_hours(m) for m in active_memberships if _available_hours(m) > 0
    )

    fairness_pct = None
    if member_hours > 0 and total_available_hours > 0 and household_total_minutes > 0:
        expected_share_minutes = household_total_minutes * (member_hours / total_available_hours)
        if expected_share_minutes > 0:
            fairness_pct = (member_minutes / expected_share_minutes) * 100

    return {
        'rolling_minutes': member_minutes,
        'household_total_minutes': household_total_minutes,
        'available_hours': member_hours,
        'total_available_hours': total_available_hours,
        'fairness_pct': fairness_pct,
    }


def project_fairness_pct(household, member, as_of, extra_minutes):
    """What `member`'s fairness_pct would become if they were credited
    an additional `extra_minutes` right now — a hypothetical projection,
    not a write. Used by #23 to warn at claim time (claiming alone
    doesn't change actual workload; only completing does, so this
    answers "if I finish this, what happens to my fairness gap?").
    Returns None when undefined (same guard as calculate_workload).
    """
    current = calculate_workload(household, member, as_of)
    member_hours = current['available_hours']
    total_available_hours = current['total_available_hours']
    if member_hours <= 0 or total_available_hours <= 0:
        return None
    projected_member_minutes = current['rolling_minutes'] + extra_minutes
    projected_household_minutes = current['household_total_minutes'] + extra_minutes
    if projected_household_minutes <= 0:
        return None
    expected_share_minutes = projected_household_minutes * (member_hours / total_available_hours)
    if expected_share_minutes <= 0:
        return None
    return (projected_member_minutes / expected_share_minutes) * 100


def household_average_fairness_pct(household, as_of):
    """The average fairness_pct across active members for whom it's
    defined — the "household average" the #23 warning threshold is
    measured against. Returns None if no member has a defined
    fairness_pct."""
    active_memberships = list(Membership.objects.filter(household=household, is_active=True))
    values = [
        calculate_workload(household, m, as_of)['fairness_pct'] for m in active_memberships
    ]
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)
