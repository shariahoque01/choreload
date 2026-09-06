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


class ChoreTemplate(models.Model):
    """A seed-data starter for the #8 chore form — global (not
    household-scoped), organized by room/task. `category_name` is a
    plain label rather than an FK to Category: Category rows are
    per-household, but a template must be usable across every household,
    so the create-from-template flow (#10) matches this label against
    the target household's own Category by name, leaving it blank for
    the user to pick if no match exists. Not editable via the UI — see
    #10's constraints.
    """

    name = models.CharField(max_length=200)
    category_name = models.CharField(max_length=100)
    default_difficulty = models.PositiveSmallIntegerField(default=1)
    default_minutes = models.PositiveIntegerField()
    default_points = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name


class ChoreDependency(models.Model):
    """Self-referential: `chore` cannot be claimed until `depends_on`'s
    current occurrence is DONE. Enforcement lives in the claim service
    (#13); this model is just the graph edge.
    """

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name='dependencies')
    depends_on = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name='dependents')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['chore', 'depends_on'], name='unique_chore_dependency'),
            models.CheckConstraint(
                condition=~models.Q(chore=models.F('depends_on')),
                name='chore_cannot_depend_on_itself',
            ),
        ]

    def clean(self):
        if self.chore_id and self.depends_on_id and self.chore_id == self.depends_on_id:
            raise ValidationError('A chore cannot depend on itself.')

    def __str__(self):
        return f'{self.chore} depends on {self.depends_on}'


class ChecklistItem(models.Model):
    """One step within a chore's optional checklist, shown on the
    completion form. Position determines display order."""

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name='checklist_items')
    label = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position']

    def __str__(self):
        return self.label


class ChoreOccurrence(models.Model):
    """One claimable/completable instance of a Chore for a given period.
    `chores/occurrences.py` is the sole writer of status/claimed_*/
    completed_* — see that module's docstring.
    """

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        CLAIMED = 'CLAIMED', 'Claimed'
        DONE = 'DONE', 'Done'
        OVERDUE = 'OVERDUE', 'Overdue'

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name='occurrences')
    period_start = models.DateField()
    due_at = models.DateTimeField(null=True, blank=True)
    window_label = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    claimed_by = models.ForeignKey(
        'households.Membership',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='claimed_occurrences',
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        'households.Membership',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='completed_occurrences',
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['chore', 'period_start'], name='unique_chore_period')
        ]

    def __str__(self):
        return f'{self.chore} ({self.period_start})'


class Contribution(models.Model):
    """One member's manually-entered share of a collaborative chore
    (#21). Only meaningful for occurrences whose `chore.is_collaborative`
    is True; the form to create one is only shown after the occurrence
    is DONE (#18) — no timer, minutes are entered manually.
    """

    occurrence = models.ForeignKey(
        ChoreOccurrence, on_delete=models.CASCADE, related_name='contributions'
    )
    member = models.ForeignKey(
        'households.Membership', on_delete=models.CASCADE, related_name='contributions'
    )
    minutes_spent = models.PositiveIntegerField()
    entered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.member} contributed {self.minutes_spent}min to {self.occurrence}'
