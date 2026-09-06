from django.conf import settings
from django.db import models


class Household(models.Model):
    """A family/group unit. Membership rows link users to it (see below)."""

    name = models.CharField(max_length=100)
    # Rotatable share link token — generation/rotation logic belongs to
    # the household-creation and rotate-code views (#4), not this model.
    join_code = models.CharField(max_length=12, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    """One user's standing in one household: role, active status, availability."""

    class Role(models.TextChoices):
        PARENT = 'PARENT', 'Parent'
        MEMBER = 'MEMBER', 'Member'

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name='memberships'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships'
    )
    # New members default to MEMBER; the household creator is explicitly
    # promoted to PARENT by the create-household view (#4), not by this default.
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    # Schema deliberately kept flexible (JSON) — the actual capture UI/shape
    # for availability is #37's job; this task only needs the columns to exist.
    available_days = models.JSONField(default=list, blank=True)
    available_hours = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['household', 'user'], name='unique_household_membership'
            )
        ]

    def __str__(self):
        return f'{self.user} in {self.household} ({self.role})'


class Pause(models.Model):
    """A member pausing one chore (chore set) or all of their chores
    (chore=null), for a date range or indefinitely (end_date=null).
    Creating one unclaims every currently-CLAIMED occurrence it covers
    (#15) via chores/occurrences.py's unclaim_occurrence — no duplicate
    write path.

    `ended_at` is set only when a member manually ends the pause early.
    Natural expiry (today > end_date) is never backfilled onto this
    field — #16 detects "did a pause just expire" on-demand by comparing
    end_date to today, not by checking ended_at.
    """

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name='pauses')
    # Null means "all of this member's chores" rather than one specific chore.
    chore = models.ForeignKey(
        'chores.Chore', on_delete=models.CASCADE, null=True, blank=True, related_name='pauses'
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        target = self.chore or 'all chores'
        return f'{self.membership} pause on {target} from {self.start_date}'
