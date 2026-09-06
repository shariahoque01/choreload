from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, TemplateView

from .forms import HouseholdCreateForm
from .models import Household, Membership
from .permissions import can_manage_members
from .services import (
    create_household,
    get_active_membership,
    join_household,
    rotate_join_code,
    set_active_household,
)


class HouseholdCreateView(LoginRequiredMixin, CreateView):
    """#4: creating a household makes the creator its PARENT, seeds
    default categories, and sets it as the new active household (#5)."""

    model = Household
    form_class = HouseholdCreateForm
    template_name = 'households/household_form.html'
    success_url = reverse_lazy('households:switch')

    def form_valid(self, form):
        household = create_household(self.request.user, form.cleaned_data['name'])
        set_active_household(self.request, household)
        self.object = household
        return redirect(self.get_success_url())


class JoinHouseholdView(LoginRequiredMixin, View):
    """#4: /join/<code>/. An invalid code is a clean 404; joining while
    already an active member is idempotent (no duplicate, no 500).
    A GET performs the join directly since this is a plain shared link,
    not a form submission — there's no confirmation step to render.
    """

    def get(self, request, code):
        household = get_object_or_404(Household, join_code=code)
        membership = join_household(request.user, household.join_code)
        set_active_household(request, membership.household)
        return redirect('households:switch')


class RotateJoinCodeView(LoginRequiredMixin, View):
    """#4: PARENT-only. Generates a new join_code, invalidating the old
    one immediately."""

    def post(self, request, household_id):
        household = get_object_or_404(Household, pk=household_id)
        if not can_manage_members(request.user, household):
            raise PermissionDenied('Only a PARENT can rotate the join code.')
        rotate_join_code(household)
        return redirect('households:switch')


class SwitchHouseholdView(LoginRequiredMixin, TemplateView):
    """#5: lists the user's active Membership rows; selecting one sets
    request.session['active_household_id']."""

    template_name = 'households/switch.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['memberships'] = Membership.objects.filter(
            user=self.request.user, is_active=True
        ).select_related('household')
        return context

    def post(self, request, *args, **kwargs):
        membership = get_object_or_404(
            Membership, pk=request.POST['membership_id'], user=request.user, is_active=True
        )
        set_active_household(request, membership.household)
        return redirect('home')
