from django import forms

from .models import Chore


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
