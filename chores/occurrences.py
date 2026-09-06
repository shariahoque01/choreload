"""On-demand generation and the claim/unclaim state machine (#12, #13, #14).

`ensure_occurrences_exist` is called by every view that reads occurrences
for a household; there is no background job (see architecture.md's
"On-demand occurrence generation" section). The functions in this module
are the sole writers of `ChoreOccurrence.status`, `claimed_by`, and
`claimed_at` — a view must never edit those fields directly.
"""

import calendar
import datetime

from django.db import transaction
from django.utils import timezone

from .models import Chore, ChoreDependency, ChoreOccurrence


def period_start_for(recurrence, today):
    """The start date of the current period for a given recurrence kind."""
    if recurrence == Chore.Recurrence.DAILY:
        return today
    if recurrence == Chore.Recurrence.WEEKLY:
        return today - datetime.timedelta(days=today.weekday())
    if recurrence == Chore.Recurrence.MONTHLY:
        return today.replace(day=1)
    raise ValueError(f'period_start_for does not support recurrence={recurrence!r}')


def _period_end(recurrence, period_start):
    """Exclusive end date of the period started by `period_start`."""
    if recurrence == Chore.Recurrence.DAILY:
        return period_start + datetime.timedelta(days=1)
    if recurrence == Chore.Recurrence.WEEKLY:
        return period_start + datetime.timedelta(days=7)
    if recurrence == Chore.Recurrence.MONTHLY:
        days_in_month = calendar.monthrange(period_start.year, period_start.month)[1]
        return period_start + datetime.timedelta(days=days_in_month)
    raise ValueError(f'_period_end does not support recurrence={recurrence!r}')


_WINDOW_LABELS = {
    Chore.Recurrence.DAILY: 'Anytime today',
    Chore.Recurrence.WEEKLY: 'Anytime this week',
    Chore.Recurrence.MONTHLY: 'Anytime this month',
}


def due_at_for(chore, period_start):
    """The aware due_at datetime for a FIXED_TIME chore's occurrence in the
    given period, or None for a WINDOW chore."""
    if chore.due_kind != Chore.DueKind.FIXED_TIME:
        return None
    naive = datetime.datetime.combine(period_start, chore.due_time)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


def window_label_for(chore):
    """The display label for a WINDOW chore's occurrence, or '' for FIXED_TIME."""
    if chore.due_kind != Chore.DueKind.WINDOW:
        return ''
    return _WINDOW_LABELS.get(chore.recurrence, 'Anytime')


def ensure_occurrences_exist(household):
    """Create today's/this-period's occurrence for every recurring chore in
    the household (idempotent via get_or_create), then flip any occurrence
    whose due_at has passed to OVERDUE (#14). Notification writes are out
    of scope here — see #30.
    """
    today = timezone.localdate()
    for chore in household.chores.exclude(recurrence=Chore.Recurrence.NONE):
        current_period = period_start_for(chore.recurrence, today)
        ChoreOccurrence.objects.get_or_create(
            chore=chore,
            period_start=current_period,
            defaults={
                'status': ChoreOccurrence.Status.AVAILABLE,
                'due_at': due_at_for(chore, current_period),
                'window_label': window_label_for(chore),
            },
        )

    now = timezone.now()
    (
        ChoreOccurrence.objects.filter(
            chore__household=household,
            status__in=[ChoreOccurrence.Status.AVAILABLE, ChoreOccurrence.Status.CLAIMED],
            due_at__isnull=False,
            due_at__lt=now,
        ).update(status=ChoreOccurrence.Status.OVERDUE)
    )


class DependencyNotDoneError(Exception):
    """Raised when a claim is attempted but a dependency's current
    occurrence isn't DONE yet."""


def _dependency_blocking(occurrence):
    """Return the first ChoreDependency blocking this occurrence's claim,
    or None if all dependencies (if any) are satisfied."""
    for dependency in ChoreDependency.objects.filter(chore=occurrence.chore):
        current = (
            ChoreOccurrence.objects.filter(
                chore=dependency.depends_on, period_start=occurrence.period_start
            )
            .order_by('-period_start')
            .first()
        )
        if current is None or current.status != ChoreOccurrence.Status.DONE:
            return dependency
    return None


@transaction.atomic
def claim_occurrence(occurrence, membership):
    """Claim an available occurrence for an active member. Any active
    member may claim at any time, even before the period starts. Blocked
    if a ChoreDependency's depends_on chore's current occurrence isn't
    DONE yet (#13)."""
    blocking = _dependency_blocking(occurrence)
    if blocking is not None:
        raise DependencyNotDoneError(
            f'"{occurrence.chore}" depends on "{blocking.depends_on}" being done first.'
        )
    occurrence.status = ChoreOccurrence.Status.CLAIMED
    occurrence.claimed_by = membership
    occurrence.claimed_at = timezone.now()
    occurrence.save(update_fields=['status', 'claimed_by', 'claimed_at'])
    return occurrence


@transaction.atomic
def unclaim_occurrence(occurrence):
    """Release a claim with no cooldown — the same member may immediately
    reclaim. Household-wide notification on unclaim is out of scope here
    (#30)."""
    occurrence.status = ChoreOccurrence.Status.AVAILABLE
    occurrence.claimed_by = None
    occurrence.claimed_at = None
    occurrence.save(update_fields=['status', 'claimed_by', 'claimed_at'])
    return occurrence


class AlreadyCompletedError(Exception):
    """Raised when completion is attempted on an occurrence that is no
    longer AVAILABLE/CLAIMED (already DONE, or OVERDUE) — including the
    losing side of a race between two simultaneous completion requests.
    """


@transaction.atomic
def complete_occurrence(occurrence, membership):
    """Mark an occurrence DONE (#18). The single-statement conditional
    UPDATE (`status__in=[AVAILABLE, CLAIMED]`) is what makes this
    idempotent under concurrency: if two requests race, the database
    only lets one UPDATE match a still-AVAILABLE/CLAIMED row, so the
    second call's `updated` count is 0 and it raises instead of
    double-writing completed_by/completed_at.
    """
    updated = ChoreOccurrence.objects.filter(
        pk=occurrence.pk,
        status__in=[ChoreOccurrence.Status.AVAILABLE, ChoreOccurrence.Status.CLAIMED],
    ).update(
        status=ChoreOccurrence.Status.DONE,
        completed_by=membership,
        completed_at=timezone.now(),
    )
    if updated == 0:
        raise AlreadyCompletedError(
            f'"{occurrence.chore}" ({occurrence.period_start}) is not AVAILABLE/CLAIMED.'
        )
    occurrence.refresh_from_db()
    return occurrence
