from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from households.models import Household
from households.permissions import can_manage_chores

from .forms import ChecklistItemFormSet, ChoreForm
from .models import Chore


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
    model = Chore
    form_class = ChoreForm
    template_name = 'chores/chore_form.html'

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
