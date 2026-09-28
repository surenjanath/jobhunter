from django.urls import path
from . import views

urlpatterns = [
    path('profile/', views.profile, name='profile'),
    path('profile', views.profile, name='profile-no-slash'),
    path('profile/resume/', views.upload_resume, name='profile-resume'),
    path('profile/resume', views.upload_resume, name='profile-resume-no-slash'),
    path('profile/overrides/', views.overrides, name='profile-overrides'),
    path('profile/overrides', views.overrides, name='profile-overrides-no-slash'),
    path('profile/prefs/', views.prefs, name='profile-prefs'),
    path('profile/prefs', views.prefs, name='profile-prefs-no-slash'),
    path('profile/reindex/', views.reindex, name='profile-reindex'),
    path('profile/enrich/', views.enrich, name='profile-enrich'),
    path('profile/versions/<int:rid>/activate/', views.activate_version, name='profile-activate'),
    path('profile/versions/<int:rid>/', views.delete_version, name='profile-version'),
    path('rescore/', views.rescore, name='rescore'),
    path('rescore', views.rescore, name='rescore-no-slash'),
    path('jobs/<path:job_id>/match/', views.job_match, name='job-match'),
    path('jobs/<path:job_id>/match', views.job_match, name='job-match-no-slash'),
]
