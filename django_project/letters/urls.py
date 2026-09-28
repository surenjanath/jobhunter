from django.urls import path
from . import views

urlpatterns = [
    path('letters/', views.list_letters, name='letters'),
    path('letters', views.list_letters, name='letters-no-slash'),
]
