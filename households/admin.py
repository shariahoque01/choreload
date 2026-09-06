from django.contrib import admin

from .models import Household, Membership, Pause

admin.site.register(Household)
admin.site.register(Membership)
admin.site.register(Pause)
