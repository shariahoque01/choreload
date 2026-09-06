from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignupForm(UserCreationForm):
    """UserCreationForm plus a display_name field.

    architecture.md calls for "no custom User model... plus display_name" —
    rather than adding a new model/table, display_name is stored on the
    stock User's existing `first_name` column.
    """

    display_name = forms.CharField(max_length=150, required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (*UserCreationForm.Meta.fields, 'display_name')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['display_name']
        if commit:
            user.save()
        return user
