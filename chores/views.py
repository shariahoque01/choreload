from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from households.models import Household
from households.permissions import can_manage_chores

from .forms import ChecklistItemFormSet, ChoreForm
from .models import Category, Chore, ChoreTemplate


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
