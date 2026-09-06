import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from chores.forms import ChoreDependencyForm, ChoreForm
from chores.models import (
    DEFAULT_CATEGORY_NAMES,
    Category,
    ChecklistItem,
    Chore,
    ChoreDependency,
    ChoreOccurrence,
    ChoreTemplate,
    seed_default_categories,
)
from households.models import Household, Membership


@pytest.fixture
def household():
    return Household.objects.create(name='The Smiths', join_code='ABC123')


@pytest.fixture
def category(household):
    return Category.objects.create(household=household, name='Kitchen')


# --- Category (#7) ---


@pytest.mark.django_db
def test_seed_default_categories_creates_fixed_set(household):
    seed_default_categories(household)

    names = set(household.categories.values_list('name', flat=True))
    assert names == set(DEFAULT_CATEGORY_NAMES)
    assert all(household.categories.values_list('is_default', flat=True))


@pytest.mark.django_db
def test_category_name_unique_per_household(household):
    Category.objects.create(household=household, name='Kitchen')

    with pytest.raises(IntegrityError):
        Category.objects.create(household=household, name='Kitchen')


@pytest.mark.django_db
def test_category_name_can_repeat_across_households():
    household_a = Household.objects.create(name='A', join_code='AAA111')
    household_b = Household.objects.create(name='B', join_code='BBB222')
    Category.objects.create(household=household_a, name='Kitchen')

    # Should not raise — uniqueness is scoped per-household.
    Category.objects.create(household=household_b, name='Kitchen')


# --- Chore (#8) ---


def _chore_form_data(category, **overrides):
    data = {
        'name': 'Wash dishes',
        'description': '',
        'category': category.pk,
        'difficulty': 1,
        'estimated_minutes': 15,
        'initial_estimate': 15,
        'priority': Chore.Priority.MEDIUM,
        'recurrence': Chore.Recurrence.DAILY,
        'due_kind': Chore.DueKind.WINDOW,
        'due_time': '',
        'point_value': 10,
        'is_collaborative': False,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_chore_form_creates_chore_for_household(household, category):
    form = ChoreForm(data=_chore_form_data(category), household=household)

    assert form.is_valid(), form.errors
    chore = form.save()

    assert chore.household == household
    assert chore.category == category


@pytest.mark.django_db
def test_member_cannot_create_or_edit_chore(client, household, category):
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)

    response = client.post(
        f'/households/{household.pk}/chores/new/', data=_chore_form_data(category)
    )

    assert response.status_code == 403
    assert not Chore.objects.filter(household=household).exists()


@pytest.mark.django_db
def test_parent_can_create_chore_via_view(client, household, category):
    user = User.objects.create_user(username='parent', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)
    client.force_login(user)

    response = client.post(
        f'/households/{household.pk}/chores/new/', data=_chore_form_data(category)
    )

    assert response.status_code == 302
    assert Chore.objects.filter(household=household, name='Wash dishes').exists()


@pytest.mark.django_db
def test_fixed_time_due_kind_requires_due_time(household, category):
    chore = Chore(
        household=household,
        name='Take out trash',
        category=category,
        estimated_minutes=5,
        initial_estimate=5,
        due_kind=Chore.DueKind.FIXED_TIME,
        due_time=None,
    )

    with pytest.raises(ValidationError):
        chore.full_clean()


@pytest.mark.django_db
def test_window_due_kind_rejects_due_time(household, category):
    chore = Chore(
        household=household,
        name='Take out trash',
        category=category,
        estimated_minutes=5,
        initial_estimate=5,
        due_kind=Chore.DueKind.WINDOW,
        due_time='08:00',
    )

    with pytest.raises(ValidationError):
        chore.full_clean()


@pytest.mark.django_db
def test_category_from_another_household_is_rejected(household, category):
    other_household = Household.objects.create(name='Other', join_code='ZZZ999')

    chore = Chore(
        household=other_household,
        name='Take out trash',
        category=category,
        estimated_minutes=5,
        initial_estimate=5,
        due_kind=Chore.DueKind.WINDOW,
    )

    with pytest.raises(ValidationError):
        chore.full_clean()


# --- ChoreDependency and ChecklistItem (#11) ---


def _make_chore(household, category, name='Chore'):
    return Chore.objects.create(
        household=household,
        name=name,
        category=category,
        estimated_minutes=10,
        initial_estimate=10,
        due_kind=Chore.DueKind.WINDOW,
    )


@pytest.mark.django_db
def test_chore_dependency_basic_crud(household, category):
    chore = _make_chore(household, category, 'Wash dishes')
    depends_on = _make_chore(household, category, 'Clear table')

    dependency = ChoreDependency.objects.create(chore=chore, depends_on=depends_on)

    assert list(chore.dependencies.all()) == [dependency]
    dependency.delete()
    assert not chore.dependencies.exists()


@pytest.mark.django_db
def test_chore_cannot_depend_on_itself(household, category):
    chore = _make_chore(household, category, 'Wash dishes')

    with pytest.raises(ValidationError):
        ChoreDependency(chore=chore, depends_on=chore).full_clean()


@pytest.mark.django_db
def test_chore_dependency_form_rejects_self_dependency(household, category):
    chore = _make_chore(household, category, 'Wash dishes')

    form = ChoreDependencyForm(data={'depends_on': chore.pk}, chore=chore)

    assert not form.is_valid()


@pytest.mark.django_db
def test_chore_dependency_form_creates_edge(household, category):
    chore = _make_chore(household, category, 'Wash dishes')
    depends_on = _make_chore(household, category, 'Clear table')

    form = ChoreDependencyForm(data={'depends_on': depends_on.pk}, chore=chore)

    assert form.is_valid(), form.errors
    dependency = form.save()
    assert dependency.chore == chore
    assert dependency.depends_on == depends_on


@pytest.mark.django_db
def test_checklist_items_ordered_by_position(household, category):
    chore = _make_chore(household, category, 'Wash dishes')
    ChecklistItem.objects.create(chore=chore, label='Rinse', position=2)
    ChecklistItem.objects.create(chore=chore, label='Scrub', position=1)
    ChecklistItem.objects.create(chore=chore, label='Dry', position=3)

    labels = list(chore.checklist_items.values_list('label', flat=True))

    assert labels == ['Scrub', 'Rinse', 'Dry']


@pytest.mark.django_db
def test_checklist_item_crud_via_chore_edit_view(client, household, category):
    user = User.objects.create_user(username='parent', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')

    data = _chore_form_data(category, name='Wash dishes')
    data.update(
        {
            'checklist_items-TOTAL_FORMS': '1',
            'checklist_items-INITIAL_FORMS': '0',
            'checklist_items-MIN_NUM_FORMS': '0',
            'checklist_items-MAX_NUM_FORMS': '1000',
            'checklist_items-0-label': 'Rinse plates',
            'checklist_items-0-position': '0',
        }
    )

    response = client.post(f'/households/{household.pk}/chores/{chore.pk}/edit/', data=data)

    assert response.status_code == 302
    assert ChecklistItem.objects.filter(chore=chore, label='Rinse plates').exists()


# --- Chore deletion (#9) ---


@pytest.mark.django_db
def test_parent_can_delete_chore(client, household, category):
    user = User.objects.create_user(username='parent', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')

    response = client.post(f'/households/{household.pk}/chores/{chore.pk}/delete/')

    assert response.status_code == 302
    assert not Chore.objects.filter(pk=chore.pk).exists()


@pytest.mark.django_db
def test_member_cannot_delete_chore(client, household, category):
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')

    response = client.post(f'/households/{household.pk}/chores/{chore.pk}/delete/')

    assert response.status_code == 403
    assert Chore.objects.filter(pk=chore.pk).exists()


@pytest.mark.django_db
def test_deleting_chore_cascades_occurrences(household, category):
    chore = _make_chore(household, category, 'Wash dishes')
    ChoreOccurrence.objects.create(chore=chore, period_start='2024-03-14')

    chore.delete()

    assert not ChoreOccurrence.objects.exists()


@pytest.mark.django_db
def test_parent_from_other_household_cannot_delete_chore(client, household, category):
    other_household = Household.objects.create(name='Other', join_code='ZZZ999')
    user = User.objects.create_user(username='parent', password='pw12345')
    Membership.objects.create(household=other_household, user=user, role=Membership.Role.PARENT)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')

    response = client.post(f'/households/{other_household.pk}/chores/{chore.pk}/delete/')

    assert response.status_code == 404
    assert Chore.objects.filter(pk=chore.pk).exists()


# --- ChoreTemplate library (#10) ---


@pytest.mark.django_db
def test_chore_template_library_is_seeded_by_migration():
    assert ChoreTemplate.objects.count() > 0
    assert ChoreTemplate.objects.filter(category_name='Kitchen').exists()


@pytest.mark.django_db
def test_create_from_template_prefills_form(client, household, category):
    user = User.objects.create_user(username='parent', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)
    client.force_login(user)
    template = ChoreTemplate.objects.create(
        name='Wash dishes', category_name='Kitchen', default_difficulty=1,
        default_minutes=15, default_points=10,
    )

    response = client.get(f'/households/{household.pk}/chores/new/?template={template.pk}')

    assert response.status_code == 200
    form = response.context['form']
    assert form.initial['name'] == 'Wash dishes'
    assert form.initial['category'] == category.pk


@pytest.mark.django_db
def test_prefilled_form_can_still_be_edited_before_saving(client, household, category):
    user = User.objects.create_user(username='parent', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)
    client.force_login(user)
    template = ChoreTemplate.objects.create(
        name='Wash dishes', category_name='Kitchen', default_difficulty=1,
        default_minutes=15, default_points=10,
    )

    response = client.post(
        f'/households/{household.pk}/chores/new/?template={template.pk}',
        data=_chore_form_data(category, name='Wash the dishes carefully'),
    )

    assert response.status_code == 302
    assert Chore.objects.filter(household=household, name='Wash the dishes carefully').exists()
