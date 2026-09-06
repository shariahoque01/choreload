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
    Contribution,
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


def _make_chore(household, category, name='Chore', **overrides):
    defaults = dict(
        household=household,
        name=name,
        category=category,
        estimated_minutes=10,
        initial_estimate=10,
        due_kind=Chore.DueKind.WINDOW,
    )
    defaults.update(overrides)
    return Chore.objects.create(**defaults)


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


# --- Occurrence claim/unclaim/complete views (#13, #18 HTTP layer) ---


@pytest.mark.django_db
def test_member_can_claim_occurrence_via_view(client, household, category):
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')
    from django.utils import timezone

    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/claim/')

    assert response.status_code == 302
    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.CLAIMED


@pytest.mark.django_db
def test_non_member_cannot_claim_occurrence(client, household, category):
    other_household = Household.objects.create(name='Other', join_code='ZZZ111')
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=other_household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')
    from django.utils import timezone

    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/claim/')

    assert response.status_code == 403
    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.AVAILABLE


@pytest.mark.django_db
def test_member_can_complete_occurrence_via_view(client, household, category):
    user = User.objects.create_user(username='alex', password='pw12345')
    membership = Membership.objects.create(
        household=household, user=user, role=Membership.Role.MEMBER
    )
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')
    from django.utils import timezone

    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/complete/')

    assert response.status_code == 302
    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.DONE
    assert occurrence.completed_by_id == membership.pk


@pytest.mark.django_db
def test_completing_already_done_occurrence_shows_error_not_500(client, household, category):
    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes')
    from django.utils import timezone

    occurrence = ChoreOccurrence.objects.create(
        chore=chore,
        period_start=timezone.localdate(),
        status=ChoreOccurrence.Status.DONE,
        completed_at=timezone.now(),
    )

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/complete/')

    assert response.status_code == 302


# --- Collaborative contributions (#21) ---


@pytest.mark.django_db
def test_contribution_form_shown_for_collaborative_done_occurrence(client, household, category):
    from django.utils import timezone

    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Clean garage', is_collaborative=True)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.DONE
    )

    response = client.get(f'/households/{household.pk}/occurrences/')

    assert response.status_code == 200
    assert f'occurrences/{occurrence.pk}/contribute/'.encode() in response.content


@pytest.mark.django_db
def test_contribution_form_hidden_for_non_collaborative_occurrence(client, household, category):
    from django.utils import timezone

    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes', is_collaborative=False)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.DONE
    )

    response = client.get(f'/households/{household.pk}/occurrences/')

    assert response.status_code == 200
    assert f'occurrences/{occurrence.pk}/contribute/'.encode() not in response.content


@pytest.mark.django_db
def test_member_can_add_contribution_to_collaborative_occurrence(client, household, category):
    from django.utils import timezone

    user = User.objects.create_user(username='alex', password='pw12345')
    membership = Membership.objects.create(
        household=household, user=user, role=Membership.Role.MEMBER
    )
    client.force_login(user)
    chore = _make_chore(household, category, 'Clean garage', is_collaborative=True)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.DONE
    )

    response = client.post(
        f'/households/{household.pk}/occurrences/{occurrence.pk}/contribute/',
        data={'minutes_spent': 20},
    )

    assert response.status_code == 302
    assert Contribution.objects.filter(
        occurrence=occurrence, member=membership, minutes_spent=20
    ).exists()


@pytest.mark.django_db
def test_cannot_add_contribution_to_non_collaborative_chore(client, household, category):
    from django.utils import timezone

    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes', is_collaborative=False)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.DONE
    )

    response = client.post(
        f'/households/{household.pk}/occurrences/{occurrence.pk}/contribute/',
        data={'minutes_spent': 20},
    )

    assert response.status_code == 403
    assert not Contribution.objects.filter(occurrence=occurrence).exists()


@pytest.mark.django_db
def test_cannot_add_contribution_before_occurrence_is_done(client, household, category):
    from django.utils import timezone

    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category, 'Clean garage', is_collaborative=True)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    response = client.post(
        f'/households/{household.pk}/occurrences/{occurrence.pk}/contribute/',
        data={'minutes_spent': 20},
    )

    assert response.status_code == 302
    assert not Contribution.objects.filter(occurrence=occurrence).exists()


# --- Parent confirmation (#20 HTTP layer) ---


@pytest.mark.django_db
def test_parent_can_confirm_completed_occurrence(client, household, category):
    from django.utils import timezone

    parent_user = User.objects.create_user(username='parent', password='pw12345')
    parent_membership = Membership.objects.create(
        household=household, user=parent_user, role=Membership.Role.PARENT
    )
    client.force_login(parent_user)
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.DONE
    )

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/confirm/')

    assert response.status_code == 302
    occurrence.refresh_from_db()
    assert occurrence.parent_confirmed_by_id == parent_membership.pk


@pytest.mark.django_db
def test_member_cannot_confirm_occurrence(client, household, category):
    from django.utils import timezone

    user = User.objects.create_user(username='alex', password='pw12345')
    Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    client.force_login(user)
    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.DONE
    )

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/confirm/')

    assert response.status_code == 403
    occurrence.refresh_from_db()
    assert occurrence.parent_confirmed_at is None


@pytest.mark.django_db
def test_confirmation_fields_stay_null_until_acted_on(household, category):
    from django.utils import timezone

    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.DONE
    )

    assert occurrence.parent_confirmed_by is None
    assert occurrence.parent_confirmed_at is None


# --- Points on completion (#25 HTTP layer) ---


@pytest.mark.django_db
def test_completing_occurrence_via_view_awards_points(client, household, category):
    from django.utils import timezone

    from chores.models import PointAward

    user = User.objects.create_user(username='alex', password='pw12345')
    membership = Membership.objects.create(
        household=household, user=user, role=Membership.Role.MEMBER
    )
    client.force_login(user)
    chore = _make_chore(household, category, 'Wash dishes', point_value=10)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/complete/')

    assert response.status_code == 302
    assert PointAward.objects.filter(occurrence=occurrence, member=membership).exists()


# --- Point revocation (#26 HTTP layer) ---


@pytest.mark.django_db
def test_parent_can_invalidate_completion(client, household, category):
    from django.utils import timezone

    from chores.models import PointAward
    from chores.occurrences import complete_occurrence
    from chores.rewards import award_points_for_completion

    parent_user = User.objects.create_user(username='parent', password='pw12345')
    parent_membership = Membership.objects.create(
        household=household, user=parent_user, role=Membership.Role.PARENT
    )
    member_user = User.objects.create_user(username='alex', password='pw12345')
    member = Membership.objects.create(
        household=household, user=member_user, role=Membership.Role.MEMBER
    )
    chore = _make_chore(household, category, 'Wash dishes', point_value=10)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)
    award_points_for_completion(occurrence, member)
    client.force_login(parent_user)

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/invalidate/')

    assert response.status_code == 302
    assert not PointAward.objects.filter(occurrence=occurrence, revoked_at__isnull=True).exists()
    assert PointAward.objects.filter(occurrence=occurrence).exists()
    assert parent_membership  # sanity: parent membership was created


@pytest.mark.django_db
def test_member_cannot_invalidate_completion(client, household, category):
    from django.utils import timezone

    from chores.models import PointAward
    from chores.occurrences import complete_occurrence
    from chores.rewards import award_points_for_completion

    user = User.objects.create_user(username='alex', password='pw12345')
    member = Membership.objects.create(household=household, user=user, role=Membership.Role.MEMBER)
    chore = _make_chore(household, category, 'Wash dishes', point_value=10)
    occurrence = ChoreOccurrence.objects.create(
        chore=chore, period_start=timezone.localdate(), status=ChoreOccurrence.Status.AVAILABLE
    )
    complete_occurrence(occurrence, member)
    award_points_for_completion(occurrence, member)
    client.force_login(user)

    response = client.post(f'/households/{household.pk}/occurrences/{occurrence.pk}/invalidate/')

    assert response.status_code == 403
    assert PointAward.objects.filter(occurrence=occurrence, revoked_at__isnull=True).exists()
