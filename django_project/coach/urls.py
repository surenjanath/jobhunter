from django.urls import path
from . import views

urlpatterns = [
    path('coach/baseline/', views.baseline, name='coach-baseline'),
    path('coach/stories/', views.stories, name='coach-stories'),
    path('coach/stories/<int:sid>/', views.story, name='coach-story'),
    path('coach/coverage/<path:job_id>/', views.coverage, name='coach-coverage'),
    path('coach/drills/', views.drills, name='coach-drills'),
    path('coach/drills/<int:did>/', views.drill, name='coach-drill'),
    path('coach/interviews/', views.real_interviews, name='coach-interviews'),
    path('coach/interviews/<int:rid>/', views.real_interview, name='coach-interview'),
    path('coach/interviews/<int:rid>/plan/', views.plan, name='coach-plan'),
    path('coach/inbox/', views.inbox, name='coach-inbox'),
    path('coach/inbox/parse/', views.inbox_parse, name='coach-inbox-parse'),
    path('coach/inbox/<int:sid>/', views.inbox_resolve, name='coach-inbox-resolve'),
    path('coach/weekly/', views.weekly, name='coach-weekly'),
    path('coach/contacts/', views.contacts, name='coach-contacts'),
    path('coach/contacts/<int:cid>/', views.contact, name='coach-contact'),
    path('coach/offers/', views.offers, name='coach-offers'),
    path('coach/offers/<int:oid>/', views.offer, name='coach-offer'),
]
