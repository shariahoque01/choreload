from django.contrib import admin

from .models import Category, ChecklistItem, Chore, ChoreDependency, ChoreOccurrence

admin.site.register(Category)
admin.site.register(Chore)
admin.site.register(ChoreDependency)
admin.site.register(ChecklistItem)
admin.site.register(ChoreOccurrence)
