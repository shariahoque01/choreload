from django.urls import include, path

from . import views

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('', include('django.contrib.auth.urls')),
]
