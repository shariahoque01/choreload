from django.urls import path

from . import views

app_name = 'households'

urlpatterns = [
    path('new/', views.HouseholdCreateView.as_view(), name='create'),
    path('switch/', views.SwitchHouseholdView.as_view(), name='switch'),
    path('<int:household_id>/rotate-code/', views.RotateJoinCodeView.as_view(), name='rotate-code'),
    path(
        '<int:household_id>/pauses/',
        views.PauseResumeListView.as_view(),
        name='pause-resume-list',
    ),
]
