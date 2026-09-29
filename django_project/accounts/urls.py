from django.urls import path
from . import views

urlpatterns = [
    path('auth/me/', views.me, name='auth-me'),
    path('auth/register/', views.register, name='auth-register'),
    path('auth/login/', views.login_view, name='auth-login'),
    path('auth/logout/', views.logout_view, name='auth-logout'),
]
