import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from chores.forms import ChoreForm
from chores.models import DEFAULT_CATEGORY_NAMES, Category, Chore, seed_default_categories
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
