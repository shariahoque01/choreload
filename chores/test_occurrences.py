import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from chores.models import Category, Chore, ChoreDependency, ChoreOccurrence
from chores.occurrences import (
    AlreadyCompletedError,
    DependencyNotDoneError,
    claim_occurrence,
    complete_occurrence,
    due_at_for,
    ensure_occurrences_exist,
    period_start_for,
    unclaim_occurrence,
    window_label_for,
)
from households.models import Household, Membership


@pytest.fixture
def household():
    return Household.objects.create(name='The Smiths', join_code='ABC123')


@pytest.fixture
def category(household):
    return Category.objects.create(household=household, name='Kitchen')


@pytest.fixture
def member(household):
    user = User.objects.create_user(username='alex', password='pw12345')
    return Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)


def _make_chore(household, category, **overrides):
    defaults = dict(
        household=household,
        name='Wash dishes',
        category=category,
        estimated_minutes=15,
        initial_estimate=15,
        recurrence=Chore.Recurrence.DAILY,
        due_kind=Chore.DueKind.WINDOW,
    )
    defaults.update(overrides)
    return Chore.objects.create(**defaults)


# --- period boundaries (#12) ---


def test_period_start_for_daily():
    today = datetime.date(2024, 3, 14)
    assert period_start_for(Chore.Recurrence.DAILY, today) == today


def test_period_start_for_weekly_is_monday():
    thursday = datetime.date(2024, 3, 14)
    assert period_start_for(Chore.Recurrence.WEEKLY, thursday) == datetime.date(2024, 3, 11)


def test_period_start_for_monthly_is_first_of_month():
    mid_month = datetime.date(2024, 3, 14)
    assert period_start_for(Chore.Recurrence.MONTHLY, mid_month) == datetime.date(2024, 3, 1)


# --- ensure_occurrences_exist (#12) ---


@pytest.mark.django_db
def test_ensure_occurrences_exist_creates_one_occurrence(household, category):
    _make_chore(household, category)

    ensure_occurrences_exist(household)

    assert ChoreOccurrence.objects.count() == 1


@pytest.mark.django_db
def test_ensure_occurrences_exist_is_idempotent(household, category):
    _make_chore(household, category)

    ensure_occurrences_exist(household)
    ensure_occurrences_exist(household)

    assert ChoreOccurrence.objects.count() == 1


@pytest.mark.django_db
def test_ensure_occurrences_exist_skips_none_recurrence(household, category):
    _make_chore(household, category, recurrence=Chore.Recurrence.NONE)

    ensure_occurrences_exist(household)

    assert ChoreOccurrence.objects.count() == 0


@pytest.mark.django_db
def test_fixed_time_chore_gets_due_at_populated(household, category):
    chore = _make_chore(
        household, category, due_kind=Chore.DueKind.FIXED_TIME, due_time=datetime.time(18, 0)
    )

    ensure_occurrences_exist(household)

    occurrence = ChoreOccurrence.objects.get(chore=chore)
    assert occurrence.due_at is not None
    assert occurrence.window_label == ''


@pytest.mark.django_db
def test_window_chore_gets_window_label_populated(household, category):
    chore = _make_chore(household, category, due_kind=Chore.DueKind.WINDOW)

    ensure_occurrences_exist(household)

    occurrence = ChoreOccurrence.objects.get(chore=chore)
    assert occurrence.due_at is None
    assert occurrence.window_label != ''


def test_due_at_for_window_chore_is_none():
    chore = Chore(due_kind=Chore.DueKind.WINDOW, recurrence=Chore.Recurrence.DAILY)
    assert due_at_for(chore, datetime.date(2024, 3, 14)) is None


def test_window_label_for_fixed_time_chore_is_blank():
    chore = Chore(due_kind=Chore.DueKind.FIXED_TIME, recurrence=Chore.Recurrence.DAILY)
    assert window_label_for(chore) == ''


# --- overdue detection (#14) ---


@pytest.mark.django_db
def test_past_due_occurrence_flips_to_overdue(household, category):
    chore = _make_chore(
        household, category, due_kind=Chore.DueKind.FIXED_TIME, due_time=datetime.time(0, 1)
    )
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate() - datetime.timedelta(days=1),
        due_at=timezone.now() - datetime.timedelta(hours=1),
        status=ChoreOccurrence.Status.AVAILABLE,
    )

    ensure_occurrences_exist(household)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.OVERDUE


@pytest.mark.django_db
def test_future_due_occurrence_is_unaffected(household, category):
    chore = _make_chore(household, category, due_kind=Chore.DueKind.FIXED_TIME, due_time=(
        datetime.time(23, 59)
    ))
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate(),
        due_at=timezone.now() + datetime.timedelta(hours=1),
        status=ChoreOccurrence.Status.AVAILABLE,
    )

    ensure_occurrences_exist(household)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE


# --- claim / unclaim service (#13) ---


@pytest.mark.django_db
def test_claim_sets_status_and_claimant(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    claim_occurrence(occurrence, member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.CLAIMED
    assert occurrence.claimed_by == member
    assert occurrence.claimed_at is not None


@pytest.mark.django_db
def test_claim_works_before_period_starts(household, category, member):
    chore = _make_chore(household, category)
    future_period = timezone.localdate() + datetime.timedelta(days=1)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=future_period, status=ChoreOccurrence.Status.AVAILABLE
    )

    claim_occurrence(occurrence, member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.CLAIMED


@pytest.mark.django_db
def test_unclaim_releases_claim(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    claim_occurrence(occurrence, member)

    unclaim_occurrence(occurrence)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE
    assert occurrence.claimed_by is None
    assert occurrence.claimed_at is None


@pytest.mark.django_db
def test_same_member_can_immediately_reclaim(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    claim_occurrence(occurrence, member)
    unclaim_occurrence(occurrence)

    claim_occurrence(occurrence, member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.CLAIMED
    assert occurrence.claimed_by == member


@pytest.mark.django_db
def test_different_member_can_claim_after_unclaim(household, category, member):
    other_user = User.objects.create_user(username='sam', password='pw12345')
    other_member = Membership.objects.create(household=household, user=other_user)
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    claim_occurrence(occurrence, member)
    unclaim_occurrence(occurrence)

    claim_occurrence(occurrence, other_member)

    occurrence.refresh_from_db()
    assert occurrence.claimed_by == other_member


@pytest.mark.django_db
def test_claim_blocked_when_dependency_not_done(household, category, member):
    chore = _make_chore(household, category, name='Wash dishes')
    depends_on = _make_chore(household, category, name='Clear table')
    ChoreDependency.objects.create(chore=chore, depends_on=depends_on)
    period = timezone.localdate()
    ChoreOccurrence.objects.create(
        chore=depends_on, period_start=period, status=ChoreOccurrence.Status.AVAILABLE
    )
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=period, status=ChoreOccurrence.Status.AVAILABLE
    )

    with pytest.raises(DependencyNotDoneError):
        claim_occurrence(occurrence, member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE


@pytest.mark.django_db
def test_claim_succeeds_once_dependency_done(household, category, member):
    chore = _make_chore(household, category, name='Wash dishes')
    depends_on = _make_chore(household, category, name='Clear table')
    ChoreDependency.objects.create(chore=chore, depends_on=depends_on)
    period = timezone.localdate()
    ChoreOccurrence.objects.create(
        chore=depends_on, period_start=period, status=ChoreOccurrence.Status.DONE
    )
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=period, status=ChoreOccurrence.Status.AVAILABLE
    )

    claim_occurrence(occurrence, member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.CLAIMED


# --- completion (#18) ---


@pytest.mark.django_db
def test_complete_sets_status_and_completer(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    complete_occurrence(occurrence, member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.DONE
    assert occurrence.completed_by_id == member.pk
    assert occurrence.completed_at is not None


@pytest.mark.django_db
def test_complete_works_from_claimed(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate(),
        status=ChoreOccurrence.Status.CLAIMED,
        claimed_by=member,
        claimed_at=timezone.now(),
    )

    complete_occurrence(occurrence, member)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.DONE


@pytest.mark.django_db
def test_cannot_complete_an_already_done_occurrence(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate(),
        status=ChoreOccurrence.Status.DONE,
        completed_by=member,
        completed_at=timezone.now(),
    )

    with pytest.raises(AlreadyCompletedError):
        complete_occurrence(occurrence, member)


@pytest.mark.django_db
def test_double_completion_race_only_applies_once(household, category, member):
    """Simulates two 'simultaneous' completion attempts against the same
    stale in-memory occurrence: the second call's conditional UPDATE
    matches zero rows and raises, proving no double-write happens."""
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    stale_copy = ChoreOccurrence.objects.get(pk=occurrence.pk)

    complete_occurrence(occurrence, member)

    with pytest.raises(AlreadyCompletedError):
        complete_occurrence(stale_copy, member)
