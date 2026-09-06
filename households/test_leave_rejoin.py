import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from chores.models import Chore, ChoreOccurrence, PointAward
from households.models import Membership
from households.services import create_household, join_household, leave_household


@pytest.fixture
def user():
    return User.objects.create_user(username='alex', password='pw12345')


@pytest.fixture
def household(user):
    creator = User.objects.create_user(username='parent', password='pw12345')
    return create_household(creator, 'The Smiths')


@pytest.fixture
def member(household, user):
    return join_household(user, household.join_code)


@pytest.fixture
def category(household):
    return household.categories.first()


def _make_chore(household, category, **overrides):
    defaults = dict(
        household=household,
        name='Wash dishes',
        category=category,
        estimated_minutes=15,
        initial_estimate=15,
        recurrence=Chore.Recurrence.DAILY,
        due_kind=Chore.DueKind.WINDOW,
        point_value=10,
    )
    defaults.update(overrides)
    return Chore.objects.create(**defaults)


# --- leave_household (#17) ---


@pytest.mark.django_db
def test_leaving_sets_inactive_and_left_at(household, member):
    leave_household(member)

    member.refresh_from_db()
    assert member.is_active is False
    assert member.left_at is not None


@pytest.mark.django_db
def test_leaving_releases_active_claim(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=datetime.date(2024, 3, 5),
        status=ChoreOccurrence.Status.CLAIMED,
        claimed_by=member,
        claimed_at=timezone.now(),
    )

    leave_household(member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE
    assert occurrence.claimed_by is None


@pytest.mark.django_db
def test_leaving_clears_completed_occurrence_attribution(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=datetime.date(2024, 3, 5),
        status=ChoreOccurrence.Status.DONE,
        completed_by=member,
        completed_at=timezone.now(),
    )

    leave_household(member)

    occurrence.refresh_from_db()
    assert occurrence.completed_by is None
    assert occurrence.completed_at is None


@pytest.mark.django_db
def test_leaving_preserves_point_awards(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=datetime.date(2024, 3, 5),
        status=ChoreOccurrence.Status.DONE,
        completed_by=member,
        completed_at=timezone.now(),
    )
    award = PointAward.objects.create(
        occurrence=occurrence, member=member, points=10, reason=PointAward.Reason.COMPLETION
    )

    leave_household(member)

    award.refresh_from_db()
    assert award.member_id == member.pk
    assert award.points == 10


# --- rejoin via join_household (#17) ---


@pytest.mark.django_db
def test_rejoin_reactivates_existing_membership(household, member):
    leave_household(member)

    rejoined = join_household(member.user, household.join_code)

    assert rejoined.pk == member.pk
    assert rejoined.is_active is True
    assert rejoined.left_at is None
    assert Membership.objects.filter(household=household, user=member.user).count() == 1


@pytest.mark.django_db
def test_rejoin_preserves_point_award_fk(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=datetime.date(2024, 3, 5),
        status=ChoreOccurrence.Status.DONE,
        completed_by=member,
        completed_at=timezone.now(),
    )
    award = PointAward.objects.create(
        occurrence=occurrence, member=member, points=10, reason=PointAward.Reason.COMPLETION
    )
    leave_household(member)

    rejoined = join_household(member.user, household.join_code)

    award.refresh_from_db()
    assert award.member_id == rejoined.pk


@pytest.mark.django_db
def test_leaving_and_rejoining_via_http_views(client, household, member):
    client.force_login(member.user)

    response = client.post(f'/households/{household.pk}/leave/')
    assert response.status_code == 302
    member.refresh_from_db()
    assert member.is_active is False

    response = client.get(f'/join/{household.join_code}/')
    assert response.status_code == 302
    member.refresh_from_db()
    assert member.is_active is True
    assert Membership.objects.filter(household=household, user=member.user).count() == 1
