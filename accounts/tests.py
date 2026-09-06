import pytest
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_signup_creates_user_with_display_name(client):
    response = client.post(
        '/signup/',
        {
            'username': 'alex',
            'password1': 'a-strong-password-123',
            'password2': 'a-strong-password-123',
            'display_name': 'Alex Smith',
        },
    )

    assert response.status_code == 302
    user = User.objects.get(username='alex')
    assert user.first_name == 'Alex Smith'
    assert user.check_password('a-strong-password-123')


@pytest.mark.django_db
def test_signup_then_login_succeeds(client):
    client.post(
        '/signup/',
        {
            'username': 'alex',
            'password1': 'a-strong-password-123',
            'password2': 'a-strong-password-123',
            'display_name': 'Alex Smith',
        },
    )

    logged_in = client.login(username='alex', password='a-strong-password-123')

    assert logged_in is True


@pytest.mark.django_db
def test_signup_rejects_duplicate_username(client):
    User.objects.create_user(username='alex', password='an-existing-password')

    response = client.post(
        '/signup/',
        {
            'username': 'alex',
            'password1': 'another-strong-password-456',
            'password2': 'another-strong-password-456',
            'display_name': 'Alex Duplicate',
        },
    )

    assert response.status_code == 200
    assert 'already exists' in response.content.decode().lower()
    assert User.objects.filter(username='alex').count() == 1


@pytest.mark.django_db
def test_login_view_is_wired_up(client):
    response = client.get('/login/')

    assert response.status_code == 200


@pytest.mark.django_db
def test_logout_view_is_wired_up(client):
    user = User.objects.create_user(username='alex', password='a-strong-password-123')
    client.force_login(user)

    response = client.post('/logout/')

    assert response.status_code == 302
