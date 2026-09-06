import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from chores.fairness import calculate_workload
from chores.models import Category, Chore, ChoreOccurrence, Contribution
from households.models import Household, Membership


@pytest.fixture
def household():
    return Household.objects.create(name='The Smiths', join_code='ABC123')


@pytest.fixture
def category(household):
    return Category.objects.create(household=household, name='Kitchen')


def _make_chore(household, category, minutes=60, **overrides):
    defaults = dict(
        household=household,
        name='Wash dishes',
        category=category,
        estimated_minutes=minutes,
        initial_estimate=minutes,
        due_kind=Chore.DueKind.WINDOW,
    )
    defaults.update(overrides)
    return Chore.objects.create(**defaults)


def _make_member(household, username, available_hours=None):
    user = User.objects.create_user(username=username, password='pw12345')
    return Membership.objects.create(
        household=household,
        user=user,
        role=Membership.Role.MEMBER,
        available_hours=available_hours or {},
    )


def _done_occurrence(chore, member, completed_at):
    return ChoreOccurrence.objects.create(
        chore=chore,
        period_start=completed_at.date(),
        status=ChoreOccurrence.Status.DONE,
        completed_by=member,
        completed_at=completed_at,
    )


@pytest.mark.django_db
def test_equal_availability_and_equal_work_is_100_percent_fair(household, category):
    alex = _make_member(household, 'alex', {'mon': 10})
    sam = _make_member(household, 'sam', {'mon': 10})
    as_of = timezone.localdate()
    now = timezone.make_aware(datetime.datetime.combine(as_of, datetime.time(12, 0)))
    chore_a = _make_chore(household, category, name='Wash dishes', minutes=60)
    chore_b = _make_chore(household, category, name='Vacuum', minutes=60)

    _done_occurrence(chore_a, alex, now)
    _done_occurrence(chore_b, sam, now)

    result = calculate_workload(household, alex, as_of)

    assert result['rolling_minutes'] == 60
    assert result['household_total_minutes'] == 120
    assert result['fairness_pct'] == pytest.approx(100.0)


@pytest.mark.django_db
def test_member_doing_double_the_expected_share_is_200_percent(household, category):
    alex = _make_member(household, 'alex', {'mon': 10})
    _make_member(household, 'sam', {'mon': 10})
    as_of = timezone.localdate()
    now = timezone.make_aware(datetime.datetime.combine(as_of, datetime.time(12, 0)))
    chore = _make_chore(household, category, minutes=120)

    _done_occurrence(chore, alex, now)
    # sam does nothing

    result = calculate_workload(household, alex, as_of)

    assert result['rolling_minutes'] == 120
    assert result['household_total_minutes'] == 120
    assert result['fairness_pct'] == pytest.approx(200.0)


@pytest.mark.django_db
def test_zero_available_hours_member_has_undefined_fairness(household, category):
    alex = _make_member(household, 'alex', {})
    _make_member(household, 'sam', {'mon': 10})
    as_of = timezone.localdate()

    result = calculate_workload(household, alex, as_of)

    assert result['fairness_pct'] is None


@pytest.mark.django_db
def test_no_household_work_in_window_is_undefined_fairness(household, category):
    alex = _make_member(household, 'alex', {'mon': 10})
    as_of = timezone.localdate()

    result = calculate_workload(household, alex, as_of)

    assert result['household_total_minutes'] == 0
    assert result['fairness_pct'] is None


@pytest.mark.django_db
def test_unclaimed_and_overdue_occurrences_excluded(household, category):
    alex = _make_member(household, 'alex', {'mon': 10})
    _make_member(household, 'sam', {'mon': 10})
    as_of = timezone.localdate()
    now = timezone.make_aware(datetime.datetime.combine(as_of, datetime.time(12, 0)))
    chore = _make_chore(household, category, minutes=60)
    done_chore = _make_chore(household, category, name='Vacuum', minutes=60)

    ChoreOccurrence.objects.create(
        chore=chore, period_start=as_of, status=ChoreOccurrence.Status.AVAILABLE
    )
    ChoreOccurrence.objects.create(
        chore=chore,
        period_start=as_of - datetime.timedelta(days=1),
        status=ChoreOccurrence.Status.OVERDUE,
    )
    _done_occurrence(done_chore, alex, now)

    result = calculate_workload(household, alex, as_of)

    assert result['rolling_minutes'] == 60
    assert result['household_total_minutes'] == 60


@pytest.mark.django_db
def test_claimed_by_never_counts_towards_workload(household, category):
    alex = _make_member(household, 'alex', {'mon': 10})
    chore = _make_chore(household, category, minutes=60)
    ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate(),
        status=ChoreOccurrence.Status.CLAIMED,
        claimed_by=alex,
        claimed_at=timezone.now(),
    )

    result = calculate_workload(household, alex, timezone.localdate())

    assert result['rolling_minutes'] == 0


@pytest.mark.django_db
def test_contribution_minutes_count_towards_workload(household, category):
    alex = _make_member(household, 'alex', {'mon': 10})
    sam = _make_member(household, 'sam', {'mon': 10})
    as_of = timezone.localdate()
    now = timezone.make_aware(datetime.datetime.combine(as_of, datetime.time(12, 0)))
    chore = _make_chore(household, category, minutes=60, is_collaborative=True)
    occurrence = _done_occurrence(chore, sam, now)
    Contribution.objects.create(occurrence=occurrence, member=alex, minutes_spent=30)

    result = calculate_workload(household, alex, as_of)

    assert result['rolling_minutes'] == 30


@pytest.mark.django_db
def test_occurrences_outside_rolling_window_excluded(household, category):
    alex = _make_member(household, 'alex', {'mon': 10})
    as_of = timezone.localdate()
    stale = timezone.make_aware(
        datetime.datetime.combine(as_of - datetime.timedelta(days=10), datetime.time(12, 0))
    )
    chore = _make_chore(household, category, minutes=60)
    _done_occurrence(chore, alex, stale)

    result = calculate_workload(household, alex, as_of)

    assert result['rolling_minutes'] == 0
