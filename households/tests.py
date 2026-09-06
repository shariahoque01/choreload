import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError

from households.models import Household, Membership


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
