from django import forms

from .models import ChecklistItem, Chore, ChoreDependency


class ChoreForm(forms.ModelForm):
    """Create/edit form for a Chore. Household + category-household match are
    validated in the view (household is fixed per-request, not user input);
    Chore.clean() enforces due_kind/due_time and category/household consistency.
    """

    class Meta:
        model = Chore
        fields = [
            'name',
            'description',
            'category',
            'difficulty',
            'estimated_minutes',
            'initial_estimate',
            'priority',
            'recurrence',
            'due_kind',
            'due_time',
            'point_value',
            'is_collaborative',
        ]

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        if household is not None:
            self.instance.household = household
            self.fields['category'].queryset = self.fields['category'].queryset.filter(
                household=household
            )

    def save(self, commit=True):
        chore = super().save(commit=False)
        if self.household is not None:
            chore.household = self.household
        if commit:
            chore.full_clean()
            chore.save()
        return chore


ChecklistItemFormSet = forms.inlineformset_factory(
    Chore, ChecklistItem, fields=['label', 'position'], extra=1, can_delete=True
)


class ChoreDependencyForm(forms.ModelForm):
    """A single 'must finish first' edge for a chore. `depends_on`'s
    queryset is restricted to the same household and excludes the chore
    itself, so self-dependency is rejected at the form layer too (the
    model's CheckConstraint/clean() is the DB-level backstop).
    """

    class Meta:
        model = ChoreDependency
        fields = ['depends_on']

    def __init__(self, *args, chore=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.chore = chore
        if chore is not None:
            self.instance.chore = chore
            self.fields['depends_on'].queryset = Chore.objects.filter(
                household=chore.household
            ).exclude(pk=chore.pk)

    def save(self, commit=True):
        dependency = super().save(commit=False)
        if self.chore is not None:
            dependency.chore = self.chore
        if commit:
            dependency.full_clean()
            dependency.save()
        return dependency
