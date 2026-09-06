from django.urls import path

from . import views

app_name = 'chores'

urlpatterns = [
    path('<int:household_id>/chores/', views.ChoreListView.as_view(), name='chore-list'),
    path('<int:household_id>/chores/new/', views.ChoreCreateView.as_view(), name='chore-create'),
    path(
        '<int:household_id>/chores/<int:pk>/edit/',
        views.ChoreUpdateView.as_view(),
        name='chore-edit',
    ),
]
