import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from chores.models import Category
from households.models import Household, Membership
from households.services import (
    ACTIVE_HOUSEHOLD_SESSION_KEY,
    create_household,
    get_active_membership,
    join_household,
    rotate_join_code,
)


@pytest.fixture
def user():
    return User.objects.create_user(username='alex', password='pw12345')


# --- create_household (#4) ---


@pytest.mark.django_db
def test_create_household_makes_creator_parent(user):
    household = create_household(user, 'The Smiths')

    membership = Membership.objects.get(household=household, user=user)
    assert membership.role == Membership.Role.PARENT
    assert household.join_code
    assert household.created_at is not None


@pytest.mark.django_db
def test_create_household_seeds_default_categories(user):
    household = create_household(user, 'The Smiths')

    assert Category.objects.filter(household=household).count() == 3


@pytest.mark.django_db
def test_create_household_generates_unique_join_codes(user):
    household_a = create_household(user, 'Household A')
    other_user = User.objects.create_user(username='sam', password='pw12345')
    household_b = create_household(other_user, 'Household B')

    assert household_a.join_code != household_b.join_code


# --- join_household (#4) ---


@pytest.mark.django_db
def test_join_household_creates_member_role(user):
    creator = User.objects.create_user(username='parent', password='pw12345')
    household = create_household(creator, 'The Smiths')

    membership = join_household(user, household.join_code)

    assert membership.household == household
    assert membership.role == Membership.Role.MEMBER


@pytest.mark.django_db
def test_join_household_invalid_code_raises_does_not_exist(user):
    with pytest.raises(Household.DoesNotExist):
        join_household(user, 'NOPE0000')


@pytest.mark.django_db
def test_join_household_is_idempotent_for_already_active_member(user):
    creator = User.objects.create_user(username='parent', password='pw12345')
    household = create_household(creator, 'The Smiths')
    join_household(user, household.join_code)

    membership = join_household(user, household.join_code)

    assert Membership.objects.filter(household=household, user=user).count() == 1
    assert membership.household == household


@pytest.mark.django_db
def test_join_view_invalid_code_returns_404(client, user):
    client.force_login(user)

    response = client.get('/join/NOPE0000/')

    assert response.status_code == 404
    assert not Membership.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_join_view_valid_code_creates_membership(client, user):
    creator = User.objects.create_user(username='parent', password='pw12345')
    household = create_household(creator, 'The Smiths')
    client.force_login(user)

    response = client.get(f'/join/{household.join_code}/')

    assert response.status_code == 302
    assert Membership.objects.filter(household=household, user=user).exists()


@pytest.mark.django_db
def test_join_view_twice_does_not_500_or_duplicate(client, user):
    creator = User.objects.create_user(username='parent', password='pw12345')
    household = create_household(creator, 'The Smiths')
    client.force_login(user)

    client.get(f'/join/{household.join_code}/')
    response = client.get(f'/join/{household.join_code}/')

    assert response.status_code == 302
    assert Membership.objects.filter(household=household, user=user).count() == 1


# --- rotate_join_code (#4) ---


@pytest.mark.django_db
def test_rotate_join_code_changes_the_code(user):
    household = create_household(user, 'The Smiths')
    old_code = household.join_code

    rotate_join_code(household)

    assert household.join_code != old_code


@pytest.mark.django_db
def test_rotate_join_code_view_restricted_to_parent(client, user):
    household = create_household(user, 'The Smiths')
    member_user = User.objects.create_user(username='member', password='pw12345')
    Membership.objects.create(household=household, user=member_user, role=Membership.Role.MEMBER)
    client.force_login(member_user)

    response = client.post(f'/households/{household.pk}/rotate-code/')

    assert response.status_code == 403


@pytest.mark.django_db
def test_rotate_join_code_view_allows_parent(client, user):
    household = create_household(user, 'The Smiths')
    old_code = household.join_code
    client.force_login(user)

    response = client.post(f'/households/{household.pk}/rotate-code/')

    assert response.status_code == 302
    household.refresh_from_db()
    assert household.join_code != old_code


@pytest.mark.django_db
def test_old_join_code_stops_working_after_rotation(client, user):
    household = create_household(user, 'The Smiths')
    old_code = household.join_code
    rotate_join_code(household)
    other_user = User.objects.create_user(username='sam', password='pw12345')
    client.force_login(other_user)

    response = client.get(f'/join/{old_code}/')

    assert response.status_code == 404


# --- active household selection (#5) ---


@pytest.mark.django_db
def test_create_household_sets_active_household(client, user):
    client.force_login(user)

    client.post(reverse('households:create'), data={'name': 'The Smiths'})

    household = Household.objects.get(name='The Smiths')
    assert client.session[ACTIVE_HOUSEHOLD_SESSION_KEY] == household.pk


@pytest.mark.django_db
def test_join_household_sets_active_household(client, user):
    creator = User.objects.create_user(username='parent', password='pw12345')
    household = create_household(creator, 'The Smiths')
    client.force_login(user)

    client.get(f'/join/{household.join_code}/')

    assert client.session[ACTIVE_HOUSEHOLD_SESSION_KEY] == household.pk


@pytest.mark.django_db
def test_get_active_membership_returns_none_when_unset(rf, user):
    request = rf.get('/')
    request.user = user
    request.session = {}

    assert get_active_membership(request) is None


@pytest.mark.django_db
def test_get_active_membership_clears_stale_session_value(rf, user):
    household = create_household(user, 'The Smiths')
    membership = Membership.objects.get(household=household, user=user)
    membership.is_active = False
    membership.left_at = None
    membership.save()

    request = rf.get('/')
    request.user = user
    request.session = {ACTIVE_HOUSEHOLD_SESSION_KEY: household.pk}

    result = get_active_membership(request)

    assert result is None
    assert ACTIVE_HOUSEHOLD_SESSION_KEY not in request.session


@pytest.mark.django_db
def test_get_active_membership_returns_real_membership(rf, user):
    household = create_household(user, 'The Smiths')

    request = rf.get('/')
    request.user = user
    request.session = {ACTIVE_HOUSEHOLD_SESSION_KEY: household.pk}

    result = get_active_membership(request)

    assert result.household == household


@pytest.mark.django_db
def test_login_with_one_active_membership_auto_sets_active(client, user):
    household = create_household(user, 'The Smiths')

    client.login(username='alex', password='pw12345')

    assert client.session[ACTIVE_HOUSEHOLD_SESSION_KEY] == household.pk


@pytest.mark.django_db
def test_login_with_zero_memberships_sets_nothing(client, user):
    client.login(username='alex', password='pw12345')

    assert ACTIVE_HOUSEHOLD_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_login_with_multiple_memberships_sets_nothing(client, user):
    create_household(user, 'Household A')
    create_household(user, 'Household B')

    client.login(username='alex', password='pw12345')

    assert ACTIVE_HOUSEHOLD_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_switch_view_lists_only_active_memberships(client, user):
    household = create_household(user, 'The Smiths')
    membership = Membership.objects.get(household=household, user=user)
    other_household = Household.objects.create(name='Left household', join_code='LEFT0000')
    Membership.objects.create(
        household=other_household, user=user, is_active=False, left_at='2024-01-01T00:00:00Z'
    )
    client.force_login(user)

    response = client.get(reverse('households:switch'))

    memberships = list(response.context['memberships'])
    assert memberships == [membership]


@pytest.mark.django_db
def test_switch_view_post_sets_active_household(client, user):
    household = create_household(user, 'The Smiths')
    membership = Membership.objects.get(household=household, user=user)
    client.force_login(user)

    response = client.post(
        reverse('households:switch'), data={'membership_id': membership.pk}
    )

    assert response.status_code == 302
    assert client.session[ACTIVE_HOUSEHOLD_SESSION_KEY] == household.pk
