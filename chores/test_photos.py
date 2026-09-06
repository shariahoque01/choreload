import io

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from chores.models import Category, Chore, ChoreOccurrence
from chores.photos import process_photo_proof
from households.models import Household, Membership


def _fake_upload(size=(3000, 2000), with_exif=True):
    image = Image.new('RGB', size, color='red')
    buffer = io.BytesIO()
    exif = image.getexif()
    if with_exif:
        exif[271] = 'Test Camera Corp'  # Make tag
    image.save(buffer, format='JPEG', exif=exif)
    buffer.seek(0)
    return SimpleUploadedFile('photo.jpg', buffer.read(), content_type='image/jpeg')


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


# --- process_photo_proof (#19) ---


def test_process_photo_proof_resizes_to_max_dimension():
    upload = _fake_upload(size=(3000, 2000))

    processed = process_photo_proof(upload)

    resized = Image.open(processed)
    assert max(resized.size) <= 1600


def test_process_photo_proof_strips_exif():
    upload = _fake_upload(with_exif=True)

    processed = process_photo_proof(upload)

    resized = Image.open(processed)
    assert resized.getexif() == {} or len(resized.getexif()) == 0


# --- HTTP completion with/without photo (#19) ---


@pytest.mark.django_db
def test_completing_without_photo_still_works(client, household, category, member, tmp_path):
    import datetime

    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(chore=chore, period_start=datetime.date(2024, 3, 5))
    client.force_login(member.user)

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        response = client.post(
            f'/households/{household.pk}/occurrences/{occurrence.pk}/complete/'
        )

    assert response.status_code == 302
    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.DONE
    assert not occurrence.photo_proof


@pytest.mark.django_db
def test_completing_with_photo_saves_processed_photo(client, household, category, member, tmp_path):
    import datetime

    chore = _make_chore(household, category)
    occurrence = ChoreOccurrence.objects.create(chore=chore, period_start=datetime.date(2024, 3, 5))
    client.force_login(member.user)
    upload = _fake_upload()

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        response = client.post(
            f'/households/{household.pk}/occurrences/{occurrence.pk}/complete/',
            {'photo_proof': upload},
            format='multipart',
        )

    assert response.status_code == 302
    occurrence.refresh_from_db()
    assert occurrence.status == ChoreOccurrence.Status.DONE
    assert occurrence.photo_proof
