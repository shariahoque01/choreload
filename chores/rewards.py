"""Points on completion (#25) and revocation (#26).

Called directly from the completion view (#18) — never at claim time,
so points are never accrued before the work is actually done.

Point formula (decision, locked in here since the issue didn't specify
one): every completion earns a base COMPLETION award of
`chore.point_value`. On top of that:

- ON_TIME: only meaningful for a FIXED_TIME chore (one with a due_at).
  A completion at or before due_at earns a bonus of
  `ON_TIME_BONUS_PCT`% of point_value (rounded down). A WINDOW chore
  has no due_at and so no concept of lateness — it never gets this
  bonus, but is never penalized for it either.
- DIFFICULTY: a flat `DIFFICULTY_BONUS_PER_LEVEL` points per difficulty
  level above the baseline of 1.
- HELPING_OTHERS: a flat `HELPING_OTHERS_BONUS` awarded when the
  member completing the occurrence isn't the member who claimed it —
  i.e. they stepped in on someone else's claimed chore.

This keeps "an on-time completion awards more points than a late one"
true for FIXED_TIME chores without inventing an unrequested penalty
system.
"""

from django.db import transaction

from .models import ChoreOccurrence, PointAward

ON_TIME_BONUS_PCT = 20
DIFFICULTY_BONUS_PER_LEVEL = 5
HELPING_OTHERS_BONUS = 10


class OccurrenceNotDoneError(Exception):
    """Raised if points are requested for an occurrence that isn't
    DONE — points are never awarded for incomplete work."""


@transaction.atomic
def award_points_for_completion(occurrence, membership):
    """Create the PointAward row(s) for a just-completed occurrence.
    Must be called after `complete_occurrence` (#18) has already set
    status=DONE — this function itself never changes occurrence state.
    """
    if occurrence.status != ChoreOccurrence.Status.DONE:
        raise OccurrenceNotDoneError(
            f'"{occurrence.chore}" ({occurrence.period_start}) is not DONE.'
        )
    chore = occurrence.chore
    awards = [
        PointAward.objects.create(
            occurrence=occurrence,
            member=membership,
            points=chore.point_value,
            reason=PointAward.Reason.COMPLETION,
        )
    ]

    on_time = (
        occurrence.due_at is not None
        and occurrence.completed_at is not None
        and occurrence.completed_at <= occurrence.due_at
    )
    if on_time:
        bonus = (chore.point_value * ON_TIME_BONUS_PCT) // 100
        if bonus > 0:
            awards.append(
                PointAward.objects.create(
                    occurrence=occurrence,
                    member=membership,
                    points=bonus,
                    reason=PointAward.Reason.ON_TIME,
                )
            )

    if chore.difficulty > 1:
        bonus = DIFFICULTY_BONUS_PER_LEVEL * (chore.difficulty - 1)
        awards.append(
            PointAward.objects.create(
                occurrence=occurrence,
                member=membership,
                points=bonus,
                reason=PointAward.Reason.DIFFICULTY,
            )
        )

    if occurrence.claimed_by_id and occurrence.claimed_by_id != membership.pk:
        awards.append(
            PointAward.objects.create(
                occurrence=occurrence,
                member=membership,
                points=HELPING_OTHERS_BONUS,
                reason=PointAward.Reason.HELPING_OTHERS,
            )
        )

    return awards


class AlreadyRevokedError(Exception):
    """Raised when revocation is attempted on an award that's already
    revoked."""


@transaction.atomic
def revoke_point_award(award, when):
    """#26: soft-revoke a PointAward — the row is never deleted, just
    excluded (via revoked_at__isnull filters) from point totals.
    """
    if award.revoked_at is not None:
        raise AlreadyRevokedError(f'PointAward {award.pk} is already revoked.')
    award.revoked_at = when
    award.save(update_fields=['revoked_at'])
    return award
