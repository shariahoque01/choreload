from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from households.models import Membership
from households.services import get_active_membership

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
    """Minimal placeholder landing page — no dashboard app exists yet.

    On every visit while logged in (#5): a stale/unset active household
    sends a user with zero active Memberships to the create/join flow,
    and a user with more than one to the switcher. A valid active
    Membership renders the (placeholder) home page normally.
    """

    template_name = 'accounts/home.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated and get_active_membership(request) is None:
            has_any_membership = Membership.objects.filter(
                user=request.user, is_active=True
            ).exists()
            if not has_any_membership:
                return redirect('households:create')
            return redirect('households:switch')
        return super().get(request, *args, **kwargs)
