import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from chores.models import Category, Chore, ChoreOccurrence, PointAward
from chores.occurrences import complete_occurrence
from chores.rewards import (
    AlreadyRevokedError,
    OccurrenceNotDoneError,
    award_points_for_completion,
    revoke_point_award,
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


@pytest.fixture
def other_member(household):
    user = User.objects.create_user(username='sam', password='pw12345')
    return Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)


def _make_chore(household, category, **overrides):
    defaults = dict(
        household=household,
        name='Wash dishes',
        category=category,
        estimated_minutes=15,
        initial_estimate=15,
        due_kind=Chore.DueKind.WINDOW,
        point_value=10,
    )
    defaults.update(overrides)
    return Chore.objects.create(**defaults)


@pytest.mark.django_db
def test_completion_awards_base_points(household, category, member):
    chore = _make_chore(household, category, point_value=10)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)

    awards = award_points_for_completion(occurrence, member)

    assert any(a.reason == PointAward.Reason.COMPLETION and a.points == 10 for a in awards)


@pytest.mark.django_db
def test_no_points_for_incomplete_occurrence(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    with pytest.raises(OccurrenceNotDoneError):
        award_points_for_completion(occurrence, member)
    assert not PointAward.objects.exists()


@pytest.mark.django_db
def test_on_time_completion_awards_more_than_late(household, category, member):
    due_chore = _make_chore(
        household, category, name='Take out trash',
        due_kind=Chore.DueKind.FIXED_TIME, due_time=datetime.time(18, 0), point_value=10,
    )
    period = timezone.localdate()

    on_time_occurrence = ChoreOccurrence.objects.create(
        chore=due_chore,
        period_start=period,
        status=ChoreOccurrence.Status.AVAILABLE,
        due_at=timezone.make_aware(datetime.datetime.combine(period, datetime.time(18, 0))),
    )
    complete_occurrence(on_time_occurrence, member)
    on_time_occurrence.completed_at = timezone.make_aware(
        datetime.datetime.combine(period, datetime.time(17, 0))
    )
    on_time_occurrence.save(update_fields=['completed_at'])
    on_time_awards = award_points_for_completion(on_time_occurrence, member)
    on_time_total = sum(a.points for a in on_time_awards)

    late_occurrence = ChoreOccurrence.objects.create(
        chore=due_chore,
        period_start=period + datetime.timedelta(days=1),
        status=ChoreOccurrence.Status.AVAILABLE,
        due_at=timezone.make_aware(
            datetime.datetime.combine(period + datetime.timedelta(days=1), datetime.time(18, 0))
        ),
    )
    complete_occurrence(late_occurrence, member)
    late_occurrence.completed_at = timezone.make_aware(
        datetime.datetime.combine(period + datetime.timedelta(days=1), datetime.time(19, 0))
    )
    late_occurrence.save(update_fields=['completed_at'])
    late_awards = award_points_for_completion(late_occurrence, member)
    late_total = sum(a.points for a in late_awards)

    assert on_time_total > late_total


@pytest.mark.django_db
def test_difficulty_bonus_awarded_above_baseline(household, category, member):
    chore = _make_chore(household, category, difficulty=3, point_value=10)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)

    awards = award_points_for_completion(occurrence, member)

    assert any(a.reason == PointAward.Reason.DIFFICULTY for a in awards)


@pytest.mark.django_db
def test_helping_others_bonus_when_completer_differs_from_claimant(
    household, category, member, other_member
):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate(),
        status=ChoreOccurrence.Status.CLAIMED,
        claimed_by=member,
        claimed_at=timezone.now(),
    )
    complete_occurrence(occurrence, other_member)

    awards = award_points_for_completion(occurrence, other_member)

    assert any(a.reason == PointAward.Reason.HELPING_OTHERS for a in awards)


@pytest.mark.django_db
def test_no_helping_others_bonus_when_completer_is_claimant(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate(),
        status=ChoreOccurrence.Status.CLAIMED,
        claimed_by=member,
        claimed_at=timezone.now(),
    )
    complete_occurrence(occurrence, member)

    awards = award_points_for_completion(occurrence, member)

    assert not any(a.reason == PointAward.Reason.HELPING_OTHERS for a in awards)


# --- Point revocation (#26) ---


@pytest.mark.django_db
def test_revoke_sets_revoked_at(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)
    award = award_points_for_completion(occurrence, member)[0]

    revoke_point_award(award, timezone.now())

    award.refresh_from_db()
    assert award.revoked_at is not None


@pytest.mark.django_db
def test_revoking_twice_raises(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)
    award = award_points_for_completion(occurrence, member)[0]
    revoke_point_award(award, timezone.now())

    with pytest.raises(AlreadyRevokedError):
        revoke_point_award(award, timezone.now())


@pytest.mark.django_db
def test_revoked_award_row_still_exists(household, category, member):
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)
    award = award_points_for_completion(occurrence, member)[0]

    revoke_point_award(award, timezone.now())

    assert PointAward.objects.filter(pk=award.pk).exists()


@pytest.mark.django_db
def test_revoked_award_excluded_from_point_total(household, category, member):
    chore = _make_chore(household, category, point_value=10)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)
    award = award_points_for_completion(occurrence, member)[0]
    revoke_point_award(award, timezone.now())

    total = PointAward.objects.filter(member=member, revoked_at__isnull=True).count()

    assert total == 0
