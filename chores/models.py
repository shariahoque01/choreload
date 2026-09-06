from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from households.models import Household


class Category(models.Model):
    """A grouping for chores within one household (e.g. Kitchen, Bathroom)."""

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    # True for the fixed set seeded by household creation (#4); False for a
    # PARENT's custom category. Not currently used to restrict deletion —
    # any can_manage_chores user may delete either kind.
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['household', 'name'], name='unique_category_per_household'
            )
        ]

    def __str__(self):
        return self.name


# The fixed set of categories every new household gets, seeded by the
# household-creation flow (#4).
DEFAULT_CATEGORY_NAMES = ['Kitchen', 'Bathroom', 'Laundry']


def seed_default_categories(household):
    """Create the default Category rows for a newly-created household."""
    Category.objects.bulk_create(
        [
            Category(household=household, name=name, is_default=True)
            for name in DEFAULT_CATEGORY_NAMES
        ]
    )


class Chore(models.Model):
    """The recipe for a recurring or one-off task. See ChoreOccurrence for
    a single claimable/completable instance of one."""

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'

    class Recurrence(models.TextChoices):
        NONE = 'NONE', 'None'
        DAILY = 'DAILY', 'Daily'
        WEEKLY = 'WEEKLY', 'Weekly'
        MONTHLY = 'MONTHLY', 'Monthly'

    class DueKind(models.TextChoices):
        FIXED_TIME = 'FIXED_TIME', 'Fixed time'
        WINDOW = 'WINDOW', 'Window'

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name='chores')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='chores')
    difficulty = models.PositiveSmallIntegerField(default=1)
    estimated_minutes = models.PositiveIntegerField()
    # Captured once at creation; #41 (deferred, post-MVP) is what would learn
    # and adjust this from real completion data. This field is never
    # overwritten by that future logic — estimated_minutes is.
    initial_estimate = models.PositiveIntegerField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    recurrence = models.CharField(
        max_length=10, choices=Recurrence.choices, default=Recurrence.NONE
    )
    due_kind = models.CharField(max_length=12, choices=DueKind.choices)
    due_time = models.TimeField(null=True, blank=True)
    point_value = models.PositiveIntegerField(default=0)
    is_collaborative = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chores_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.due_kind == self.DueKind.FIXED_TIME and self.due_time is None:
            raise ValidationError('due_time is required when due_kind is FIXED_TIME.')
        if self.due_kind == self.DueKind.WINDOW and self.due_time is not None:
            raise ValidationError('due_time must be blank when due_kind is WINDOW.')
        if self.category_id and self.category.household_id != self.household_id:
            raise ValidationError('category must belong to the same household as the chore.')

    def __str__(self):
        return self.name
