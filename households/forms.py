from django import forms

from .models import Household


class HouseholdCreateForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = ['name']
