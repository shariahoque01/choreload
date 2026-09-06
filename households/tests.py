import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError

from households.models import Household, Membership
from households.permissions import can_approve, can_manage_chores, can_manage_members


@pytest.mark.django_db
def test_household_has_expected_fields():
    household = Household.objects.create(name='The Smiths', join_code='ABC123')

    assert household.name == 'The Smiths'
    assert household.join_code == 'ABC123'
    assert household.created_at is not None


@pytest.mark.django_db
def test_membership_default_role_is_member():
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')

    membership = Membership.objects.create(household=household, user=user)

    assert membership.role == Membership.Role.MEMBER
    assert membership.is_active is True
    assert membership.joined_at is not None
    assert membership.left_at is None


@pytest.mark.django_db
def test_membership_household_user_pair_is_unique():
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user)

    with pytest.raises(IntegrityError):
        Membership.objects.create(household=household, user=user)


@pytest.mark.parametrize('predicate', [can_manage_chores, can_manage_members])
@pytest.mark.django_db
def test_household_predicate_true_for_active_parent(predicate):
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)

    assert predicate(user, household) is True


@pytest.mark.parametrize('predicate', [can_manage_chores, can_manage_members])
@pytest.mark.django_db
def test_household_predicate_false_for_active_member(predicate):
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)

    assert predicate(user, household) is False


@pytest.mark.parametrize('predicate', [can_manage_chores, can_manage_members])
@pytest.mark.django_db
def test_household_predicate_false_for_no_membership(predicate):
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')

    assert predicate(user, household) is False


@pytest.mark.parametrize('predicate', [can_manage_chores, can_manage_members])
@pytest.mark.django_db
def test_household_predicate_false_for_inactive_parent(predicate):
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(
        household=household,
        user=user,
        role=Membership.Role.PARENT,
        is_active=False,
    )

    assert predicate(user, household) is False


def _make_occurrence(household):
    from chores.models import Category, Chore, ChoreOccurrence

    category = Category.objects.create(household=household, name='Kitchen')
    chore = Chore.objects.create(
        household=household,
        name='Wash dishes',
        category=category,
        estimated_minutes=15,
        initial_estimate=15,
        due_kind=Chore.DueKind.WINDOW,
    )
    return ChoreOccurrence.objects.create(chore=chore, period_start='2024-03-14')


@pytest.mark.django_db
def test_can_approve_true_for_active_parent():
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.PARENT)
    occurrence = _make_occurrence(household)

    assert can_approve(user, occurrence) is True


@pytest.mark.django_db
def test_can_approve_false_for_active_member():
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    occurrence = _make_occurrence(household)

    assert can_approve(user, occurrence) is False


@pytest.mark.django_db
def test_can_approve_false_for_no_membership():
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    occurrence = _make_occurrence(household)

    assert can_approve(user, occurrence) is False


@pytest.mark.django_db
def test_can_approve_false_for_inactive_parent():
    household = Household.objects.create(name='The Smiths', join_code='ABC123')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(
        household=household, user=user, role=Membership.Role.PARENT, is_active=False
    )
    occurrence = _make_occurrence(household)

    assert can_approve(user, occurrence) is False
