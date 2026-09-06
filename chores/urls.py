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
    path(
        '<int:household_id>/chores/<int:pk>/delete/',
        views.ChoreDeleteView.as_view(),
        name='chore-delete',
    ),
    path(
        '<int:household_id>/occurrences/',
        views.OccurrenceListView.as_view(),
        name='occurrence-list',
    ),
    path(
        '<int:household_id>/occurrences/<int:pk>/claim/',
        views.ClaimOccurrenceView.as_view(),
        name='occurrence-claim',
    ),
    path(
        '<int:household_id>/occurrences/<int:pk>/unclaim/',
        views.UnclaimOccurrenceView.as_view(),
        name='occurrence-unclaim',
    ),
    path(
        '<int:household_id>/occurrences/<int:pk>/complete/',
        views.CompleteOccurrenceView.as_view(),
        name='occurrence-complete',
    ),
    path(
        '<int:household_id>/occurrences/<int:pk>/contribute/',
        views.AddContributionView.as_view(),
        name='occurrence-contribute',
    ),
    path(
        '<int:household_id>/occurrences/<int:pk>/confirm/',
        views.ConfirmOccurrenceView.as_view(),
        name='occurrence-confirm',
    ),
    path(
        '<int:household_id>/occurrences/<int:pk>/invalidate/',
        views.InvalidateCompletionView.as_view(),
        name='occurrence-invalidate',
    ),
]
