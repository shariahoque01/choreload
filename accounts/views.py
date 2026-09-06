from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from .forms import SignupForm


class SignupView(CreateView):
    """Plain UserCreationForm + display_name. A successful signup does not
    auto-login the user (Django's default); it redirects to the login page
    so "successful signup immediately allows login" is a next-step action,
    not an automatic session.
    """

    form_class = SignupForm
    template_name = 'registration/signup.html'
    success_url = reverse_lazy('login')


class HomeView(TemplateView):
    """Minimal placeholder landing page — no dashboard app exists yet."""

    template_name = 'accounts/home.html'
