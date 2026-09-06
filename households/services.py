"""Household creation/join/rotate business logic (#4) and active-household
session helpers (#5). Kept out of views.py so it's testable without the
request/response cycle.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .join_codes import unique_join_code
from .models import Household, Membership, Pause


def create_household(user, name):
    """Create a Household, make `user` its PARENT, and seed default
    categories (#7). Category seeding is deferred-imported to avoid a
    module-load-time dependency from households -> chores.
    """
    with transaction.atomic():
        household = Household.objects.create(name=name, join_code=unique_join_code(Household))
        Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)

        from chores.models import seed_default_categories

        seed_default_categories(household)
    return household


def join_household(user, code):
    """Join `user` to the household with the given join_code as a MEMBER.

    Raises Household.DoesNotExist for an invalid/unknown code — the view
    turns that into a 404. Idempotent for a user who already holds an
    active Membership in that household: get_or_create returns the
    existing row rather than raising or creating a duplicate.

    A user who previously left (#17) has a matching inactive Membership
    row already, so get_or_create finds it instead of making a new one;
    this reactivates it in place (is_active=True, left_at cleared) so
    every FK into it — PointAward, and eventually MemberBadge/Streak
    once #27/#28 exist — keeps pointing at the same row rather than a
    fresh one.
    """
    household = Household.objects.get(join_code=code)
    membership, created = Membership.objects.get_or_create(
        household=household, user=user, defaults={'role': Membership.Role.MEMBER}
    )
    if not created and not membership.is_active:
        membership.is_active = True
        membership.left_at = None
        membership.save(update_fields=['is_active', 'left_at'])
    return membership


def rotate_join_code(household):
    """Generate a new join_code for the household, invalidating the old
    one immediately (it's simply no longer stored anywhere)."""
    household.join_code = unique_join_code(Household)
    household.save(update_fields=['join_code'])
    return household


ACTIVE_HOUSEHOLD_SESSION_KEY = 'active_household_id'


def set_active_household(request, household):
    request.session[ACTIVE_HOUSEHOLD_SESSION_KEY] = household.pk


def get_active_membership(request):
    """Re-validate the session's active household against a real active
    Membership for the current user. Clears the stale session key (e.g.
    after the member left, #17) and returns None if it no longer holds.
    """
    household_id = request.session.get(ACTIVE_HOUSEHOLD_SESSION_KEY)
    if household_id is None:
        return None
    membership = (
        Membership.objects.filter(household_id=household_id, user=request.user, is_active=True)
        .select_related('household')
        .first()
    )
    if membership is None:
        request.session.pop(ACTIVE_HOUSEHOLD_SESSION_KEY, None)
        return None
    return membership


def auto_set_active_household_on_login(request, user):
    """Called from the user_logged_in signal (#5): if the user has
    exactly one active Membership, make it the active household so they
    skip the switcher. Zero or multiple memberships are left for the
    login view/switcher to handle.
    """
    memberships = list(Membership.objects.filter(user=user, is_active=True)[:2])
    if len(memberships) == 1:
        set_active_household(request, memberships[0].household)


@transaction.atomic
def create_pause(membership, chore, start_date, end_date):
    """Pause `chore` (or all of the member's chores, if `chore` is None)
    for `membership`, from `start_date` to `end_date` (indefinite if
    `end_date` is None). Immediately unclaims every currently-CLAIMED
    occurrence the pause covers, reusing chores/occurrences.py's
    unclaim_occurrence — no duplicate write path for status/claimed_*
    (#13). Deferred-imported to avoid a module-load-time dependency
    from households -> chores.
    """
    from chores.models import ChoreOccurrence
    from chores.occurrences import unclaim_occurrence

    pause = Pause.objects.create(
        membership=membership, chore=chore, start_date=start_date, end_date=end_date
    )

    covered = ChoreOccurrence.objects.filter(
        claimed_by=membership,
        status=ChoreOccurrence.Status.CLAIMED,
        period_start__gte=start_date,
    )
    if end_date is not None:
        covered = covered.filter(period_start__lte=end_date)
    if chore is not None:
        covered = covered.filter(chore=chore)
    else:
        covered = covered.filter(chore__household=membership.household)

    for occurrence in covered:
        unclaim_occurrence(occurrence)

    return pause


def end_pause(pause):
    """Manually end a pause early. Natural expiry (end_date passed) is
    never routed through here — see Pause's docstring and #16."""
    pause.ended_at = timezone.now()
    pause.save(update_fields=['ended_at'])
    return pause


def pauses_needing_decision(membership):
    """This member's pauses that have ended and need a resume decision
    (#16): manually-ended ones (ended_at set) plus naturally-expired
    ones (end_date <= today, ended_at still null). Expiry is detected
    here on-demand, every read — nothing backfills ended_at for it,
    consistent with #15's Pause docstring.
    """
    today = timezone.localdate()
    return (
        Pause.objects.filter(membership=membership)
        .filter(Q(ended_at__isnull=False) | Q(end_date__lte=today, ended_at__isnull=True))
        .order_by('-start_date')
    )


@transaction.atomic
def leave_household(membership):
    """A member leaves their household (#17): deactivates the
    Membership rather than deleting it, so it can be reactivated by
    join_household() later without losing any FK into it.

    - Releases every currently-CLAIMED occurrence via
      chores/occurrences.py's unclaim_occurrence() (#13) — no
      duplicate write path.
    - Clears completed_by/completed_at on this member's completed
      occurrences. This erases *attribution* only: the ChoreOccurrence
      row itself is not deleted (deleting it would cascade-delete its
      PointAward rows, since PointAward.occurrence is on_delete=CASCADE
      — that would violate "leaving preserves PointAward rows" below).
    - PointAward rows are left untouched, so points earned survive the
      member leaving. MemberBadge/Streak don't exist yet (#27, #28 are
      post-MVP); once they do, they should follow the same rule — FK to
      Membership, never touched by this function.
    """
    from chores.models import ChoreOccurrence
    from chores.occurrences import unclaim_occurrence

    claimed = ChoreOccurrence.objects.filter(
        claimed_by=membership, status=ChoreOccurrence.Status.CLAIMED
    )
    for occurrence in claimed:
        unclaim_occurrence(occurrence)

    ChoreOccurrence.objects.filter(completed_by=membership).update(
        completed_by=None, completed_at=None
    )

    membership.is_active = False
    membership.left_at = timezone.now()
    membership.save(update_fields=['is_active', 'left_at'])
    return membership
