from django.urls import path
from . import views

urlpatterns = [
    path('brief/', views.brief, name='brief'),
    path('brief', views.brief, name='brief-no-slash'),
    path('analytics/', views.dashboard, name='analytics'),
    path('analytics', views.dashboard, name='analytics-no-slash'),
    path('insights/', views.insights, name='insights'),
    path('insights', views.insights, name='insights-no-slash'),
    path('resume/', views.resume, name='resume'),
    path('resume', views.resume, name='resume-no-slash'),
    path('coach/brief/', views.coach_brief, name='coach-brief'),
    path('coach/brief', views.coach_brief, name='coach-brief-no-slash'),
]
