import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from chores.models import Category, Chore, ChoreOccurrence
from households.models import Household, Membership, Pause
from households.services import create_pause, end_pause


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


def _claim(chore, member, period_start):
    return ChoreOccurrence.objects.create(
        chore=chore,
        period_start=period_start,
        status=ChoreOccurrence.Status.CLAIMED,
        claimed_by=member,
        claimed_at=timezone.now(),
    )


@pytest.mark.django_db
def test_pause_model_has_expected_fields(household, category, member):
    chore = _make_chore(household, category)
    pause = Pause.objects.create(
        membership=member, chore=chore, start_date=datetime.date(2024, 3, 1)
    )

    assert pause.membership == member
    assert pause.chore == chore
    assert pause.end_date is None
    assert pause.ended_at is None


@pytest.mark.django_db
def test_pause_can_target_all_chores_with_null_chore(household, member):
    pause = Pause.objects.create(
        membership=member, chore=None, start_date=datetime.date(2024, 3, 1)
    )

    assert pause.chore is None


@pytest.mark.django_db
def test_creating_a_pause_unclaims_covered_claimed_occurrence(household, category, member):
    chore = _make_chore(household, category)
    occurrence = _claim(chore, member, datetime.date(2024, 3, 5))

    create_pause(member, chore, datetime.date(2024, 3, 1), datetime.date(2024, 3, 10))

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE
    assert occurrence.claimed_by is None
    assert occurrence.claimed_at is None


@pytest.mark.django_db
def test_indefinite_pause_releases_claims_with_no_end_date(household, category, member):
    chore = _make_chore(household, category)
    occurrence = _claim(chore, member, datetime.date(2024, 3, 5))

    create_pause(member, chore, datetime.date(2024, 3, 1), None)

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE


@pytest.mark.django_db
def test_pausing_all_chores_releases_claims_across_every_chore(household, category, member):
    chore_a = _make_chore(household, category, name='Wash dishes')
    chore_b = _make_chore(household, category, name='Take out trash')
    occurrence_a = _claim(chore_a, member, datetime.date(2024, 3, 5))
    occurrence_b = _claim(chore_b, member, datetime.date(2024, 3, 5))

    create_pause(member, None, datetime.date(2024, 3, 1), datetime.date(2024, 3, 10))

    occurrence_a.refresh_from_db()
    occurrence_b.refresh_from_db()
    assert occurrence_a.status == ChoreOccurrence.Status.AVAILABLE
    assert occurrence_b.status == ChoreOccurrence.Status.AVAILABLE


@pytest.mark.django_db
def test_pause_does_not_release_claims_outside_its_date_range(household, category, member):
    chore = _make_chore(household, category)
    occurrence = _claim(chore, member, datetime.date(2024, 4, 1))

    create_pause(member, chore, datetime.date(2024, 3, 1), datetime.date(2024, 3, 10))

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.CLAIMED


@pytest.mark.django_db
def test_pause_does_not_release_another_members_claim(household, category, member):
    other_user = User.objects.create_user(username='sam', password='pw12345')
    other = Membership.objects.create(
        household=household, user=other_user, role=Membership.Role.MEMBER
    )
    chore = _make_chore(household, category)
    occurrence = _claim(chore, other, datetime.date(2024, 3, 5))

    create_pause(member, chore, datetime.date(2024, 3, 1), datetime.date(2024, 3, 10))

    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.CLAIMED


@pytest.mark.django_db
def test_ending_a_pause_sets_ended_at(household, category, member):
    chore = _make_chore(household, category)
    pause = create_pause(member, chore, datetime.date(2024, 3, 1), None)

    end_pause(pause)

    pause.refresh_from_db()
    assert pause.ended_at is not None


@pytest.mark.django_db
def test_expired_pause_leaves_ended_at_unset(household, category, member):
    chore = _make_chore(household, category)
    pause = create_pause(
        member, chore, datetime.date(2020, 1, 1), datetime.date(2020, 1, 31)
    )

    pause.refresh_from_db()
    assert pause.ended_at is None


# --- resume prompt (#16) ---


@pytest.mark.django_db
def test_pauses_needing_decision_includes_manually_ended_pause(household, category, member):
    from households.services import pauses_needing_decision

    chore = _make_chore(household, category)
    pause = Pause.objects.create(
        membership=member, chore=chore, start_date=datetime.date(2024, 1, 1)
    )
    end_pause(pause)

    assert pause in pauses_needing_decision(member)


@pytest.mark.django_db
def test_pauses_needing_decision_includes_naturally_expired_pause(household, category, member):
    from households.services import pauses_needing_decision

    chore = _make_chore(household, category)
    pause = Pause.objects.create(
        membership=member,
        chore=chore,
        start_date=datetime.date(2020, 1, 1),
        end_date=datetime.date(2020, 1, 31),
    )

    assert pause in pauses_needing_decision(member)


@pytest.mark.django_db
def test_pauses_needing_decision_excludes_active_pause(household, category, member):
    from households.services import pauses_needing_decision

    chore = _make_chore(household, category)
    future = timezone.localdate() + datetime.timedelta(days=30)
    pause = Pause.objects.create(
        membership=member, chore=chore, start_date=timezone.localdate(), end_date=future
    )

    assert pause not in pauses_needing_decision(member)


@pytest.mark.django_db
def test_pauses_needing_decision_excludes_indefinite_unended_pause(household, category, member):
    from households.services import pauses_needing_decision

    chore = _make_chore(household, category)
    pause = Pause.objects.create(
        membership=member, chore=chore, start_date=timezone.localdate(), end_date=None
    )

    assert pause not in pauses_needing_decision(member)


@pytest.mark.django_db
def test_viewing_resume_prompt_does_not_auto_reclaim_anything(client, household, category, member):
    chore = _make_chore(household, category)
    occurrence = _claim(chore, member, datetime.date(2024, 3, 5))
    create_pause(member, chore, datetime.date(2024, 3, 1), datetime.date(2024, 3, 10))

    client.force_login(member.user)
    response = client.get(f'/households/{household.pk}/pauses/')

    assert response.status_code == 200
    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE
