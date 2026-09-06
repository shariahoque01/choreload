"""All authorization lives here as plain predicate functions, per
architecture.md's Permissions section. No Django groups/permissions
machinery, no DRF permission classes.
"""

from .models import Membership


def _has_active_role(user, household, role):
    if not user.is_authenticated:
        return False
    return Membership.objects.filter(
        household=household, user=user, is_active=True, role=role
    ).exists()


def can_manage_chores(user, household):
    """PARENT-only: create/edit/delete a chore, manage categories."""
    return _has_active_role(user, household, Membership.Role.PARENT)


def can_manage_members(user, household):
    """PARENT-only: rotate join code, promote/demote members."""
    return _has_active_role(user, household, Membership.Role.PARENT)


def can_approve(user, occurrence):
    """PARENT-only: confirm a completion, invalidate a completed occurrence.

    Resolves the household from the occurrence's chore internally so
    call sites don't need to look it up themselves.
    """
    return _has_active_role(user, occurrence.chore.household, Membership.Role.PARENT)
