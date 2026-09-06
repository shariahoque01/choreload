from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from households.models import Household, Membership
from households.permissions import can_approve, can_manage_chores, is_active_member

from .forms import ChecklistItemFormSet, ChoreForm, ContributionForm
from .models import Category, Chore, ChoreOccurrence, ChoreTemplate, PointAward
from .occurrences import (
    AlreadyCompletedError,
    DependencyNotDoneError,
    NotDoneYetError,
    claim_occurrence,
    complete_occurrence,
    confirm_occurrence,
    ensure_occurrences_exist,
    unclaim_occurrence,
)
from .rewards import award_points_for_completion, revoke_point_award


class HouseholdChoreMixin(LoginRequiredMixin):
    """Resolves `self.household` from the `household_id` URL kwarg and
    enforces can_manage_chores (#6) before allowing the request through.
    """

    def dispatch(self, request, *args, **kwargs):
        self.household = get_object_or_404(Household, pk=kwargs['household_id'])
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not can_manage_chores(request.user, self.household):
            raise PermissionDenied('Only a PARENT can manage chores.')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['household'] = self.household
        return kwargs

    def get_success_url(self):
        return reverse_lazy('chores:chore-list', kwargs={'household_id': self.household.pk})


class ChoreListView(LoginRequiredMixin, ListView):
    model = Chore
    template_name = 'chores/chore_list.html'
    context_object_name = 'chores'

    def get_queryset(self):
        return Chore.objects.filter(household_id=self.kwargs['household_id'])


class ChoreCreateView(HouseholdChoreMixin, CreateView):
    """A plain create form, or pre-filled from a #10 ChoreTemplate via
    ?template=<id>. The template's category_name is matched against this
    household's own Category by name; if none matches, category is left
    blank for the user to pick. The pre-filled form is still fully
    editable before saving — nothing is auto-submitted.
    """

    model = Chore
    form_class = ChoreForm
    template_name = 'chores/chore_form.html'

    def get_initial(self):
        initial = super().get_initial()
        template_id = self.request.GET.get('template')
        if template_id:
            chore_template = get_object_or_404(ChoreTemplate, pk=template_id)
            matching_category = Category.objects.filter(
                household=self.household, name=chore_template.category_name
            ).first()
            initial.update(
                {
                    'name': chore_template.name,
                    'difficulty': chore_template.default_difficulty,
                    'estimated_minutes': chore_template.default_minutes,
                    'initial_estimate': chore_template.default_minutes,
                    'point_value': chore_template.default_points,
                    'category': matching_category.pk if matching_category else None,
                }
            )
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class ChoreUpdateView(HouseholdChoreMixin, UpdateView):
    """Edit a chore's own fields, plus basic CRUD on its checklist items
    (#11) via an inline formset. ChoreDependency edges are managed
    separately through ChoreDependencyForm — not embedded here, since a
    chore may have several dependency edges and this keeps the main
    edit form simple.
    """

    model = Chore
    form_class = ChoreForm
    template_name = 'chores/chore_form.html'

    def get_queryset(self):
        return Chore.objects.filter(household=self.household)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'checklist_formset' not in context:
            context['checklist_formset'] = ChecklistItemFormSet(instance=self.object)
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        checklist_formset = ChecklistItemFormSet(request.POST, instance=self.object)
        if form.is_valid() and checklist_formset.is_valid():
            self.object = form.save()
            checklist_formset.instance = self.object
            checklist_formset.save()
            return redirect(self.get_success_url())
        return self.render_to_response(
            self.get_context_data(form=form, checklist_formset=checklist_formset)
        )


class ChoreDeleteView(HouseholdChoreMixin, DeleteView):
    """#9: hard delete, PARENT-only (via HouseholdChoreMixin's
    can_manage_chores check). Cascades to ChoreOccurrence and anything
    that references it (Contribution, PointAward, Streak, as those
    models land) via each FK's on_delete=CASCADE — no separate cleanup
    code, no soft-delete flag.
    """

    model = Chore
    template_name = 'chores/chore_confirm_delete.html'

    def get_form_kwargs(self):
        # DeleteView's confirmation form is a plain Form, not ChoreForm —
        # skip HouseholdChoreMixin's `household` kwarg injection, but keep
        # the usual data/files binding so the empty confirmation form is
        # still a *bound*, valid form on POST.
        kwargs = {'initial': self.get_initial()}
        if self.request.method in ('POST', 'PUT'):
            kwargs.update({'data': self.request.POST, 'files': self.request.FILES})
        return kwargs

    def get_queryset(self):
        # Scoped to this household: a PARENT from household A cannot
        # delete a Chore belonging to household B (get_object_or_404
        # inside DeleteView.get_object() 404s instead of leaking across
        # households).
        return Chore.objects.filter(household=self.household)


class HouseholdMemberMixin(LoginRequiredMixin):
    """Resolves `self.household` and enforces `is_active_member` — used
    for occurrence actions (#13, #18) any active member may perform,
    unlike `HouseholdChoreMixin`'s PARENT-only chore management.
    """

    def dispatch(self, request, *args, **kwargs):
        self.household = get_object_or_404(Household, pk=kwargs['household_id'])
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not is_active_member(request.user, self.household):
            raise PermissionDenied('Only an active member of this household may do that.')
        self.membership = Membership.objects.get(
            household=self.household, user=request.user, is_active=True
        )
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy(
            'chores:occurrence-list', kwargs={'household_id': self.household.pk}
        )


class OccurrenceListView(HouseholdMemberMixin, ListView):
    """Lists this period's occurrences, generating them on-demand (#12)
    on every read — no background job."""

    template_name = 'chores/occurrence_list.html'
    context_object_name = 'occurrences'

    def get_queryset(self):
        ensure_occurrences_exist(self.household)
        return (
            ChoreOccurrence.objects.filter(chore__household=self.household)
            .select_related('chore', 'claimed_by', 'completed_by')
            .order_by('chore__name', 'period_start')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['household_id'] = self.household.pk
        return context


class ClaimOccurrenceView(HouseholdMemberMixin, View):
    def post(self, request, *args, **kwargs):
        occurrence = get_object_or_404(
            ChoreOccurrence, pk=kwargs['pk'], chore__household=self.household
        )
        try:
            _occurrence, warning = claim_occurrence(occurrence, self.membership)
        except DependencyNotDoneError as exc:
            messages.error(request, str(exc))
        else:
            if warning:
                messages.warning(request, warning)
        return redirect(self.get_success_url())


class UnclaimOccurrenceView(HouseholdMemberMixin, View):
    def post(self, request, *args, **kwargs):
        occurrence = get_object_or_404(
            ChoreOccurrence, pk=kwargs['pk'], chore__household=self.household
        )
        unclaim_occurrence(occurrence)
        return redirect(self.get_success_url())


class CompleteOccurrenceView(HouseholdMemberMixin, View):
    """#18: the single funnel point for completion. #19-#21, #25, #27,
    #28 hook into this call site (photo proof, collaborative
    contributions, points, etc.) rather than re-implementing completion.
    """

    def post(self, request, *args, **kwargs):
        occurrence = get_object_or_404(
            ChoreOccurrence, pk=kwargs['pk'], chore__household=self.household
        )
        try:
            complete_occurrence(occurrence, self.membership)
        except AlreadyCompletedError as exc:
            messages.error(request, str(exc))
        else:
            award_points_for_completion(occurrence, self.membership)
        return redirect(self.get_success_url())


class AddContributionView(HouseholdMemberMixin, View):
    """#21: entering minutes for a collaborative chore, after the
    occurrence is DONE. Rejected (400) for a non-collaborative chore or
    an occurrence that isn't DONE yet — the completion form itself only
    shows this action when both hold, but the view enforces it too.
    """

    def post(self, request, *args, **kwargs):
        occurrence = get_object_or_404(
            ChoreOccurrence, pk=kwargs['pk'], chore__household=self.household
        )
        if not occurrence.chore.is_collaborative:
            raise PermissionDenied('This chore is not collaborative.')
        if occurrence.status != ChoreOccurrence.Status.DONE:
            messages.error(request, 'Contributions can only be added after completion.')
            return redirect(self.get_success_url())
        form = ContributionForm(request.POST)
        if form.is_valid():
            contribution = form.save(commit=False)
            contribution.occurrence = occurrence
            contribution.member = self.membership
            contribution.save()
        else:
            messages.error(request, 'Enter a valid number of minutes.')
        return redirect(self.get_success_url())


class ConfirmOccurrenceView(HouseholdMemberMixin, View):
    """#20: a PARENT confirms a DONE occurrence, gated by can_approve
    (#6). A MEMBER gets 403. Works independent of whether a photo was
    attached (#19); confirmation fields stay null until acted on.
    """

    def post(self, request, *args, **kwargs):
        occurrence = get_object_or_404(
            ChoreOccurrence, pk=kwargs['pk'], chore__household=self.household
        )
        if not can_approve(request.user, occurrence):
            raise PermissionDenied('Only a PARENT can confirm a completion.')
        try:
            confirm_occurrence(occurrence, self.membership)
        except NotDoneYetError as exc:
            messages.error(request, str(exc))
        return redirect(self.get_success_url())


class InvalidateCompletionView(HouseholdMemberMixin, View):
    """#26: a PARENT invalidates a completed occurrence, gated by
    can_approve. Soft-revokes every not-yet-revoked PointAward tied to
    the occurrence — rows are never deleted, just excluded from totals
    via revoked_at.
    """

    def post(self, request, *args, **kwargs):
        occurrence = get_object_or_404(
            ChoreOccurrence, pk=kwargs['pk'], chore__household=self.household
        )
        if not can_approve(request.user, occurrence):
            raise PermissionDenied('Only a PARENT can invalidate a completion.')
        now = timezone.now()
        for award in PointAward.objects.filter(occurrence=occurrence, revoked_at__isnull=True):
            revoke_point_award(award, now)
        return redirect(self.get_success_url())
