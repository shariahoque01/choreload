from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .services import auto_set_active_household_on_login


@receiver(user_logged_in)
def set_active_household_on_login(sender, request, user, **kwargs):
    auto_set_active_household_on_login(request, user)
