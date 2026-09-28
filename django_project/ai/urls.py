from django.urls import path
from . import views

urlpatterns = [
    path('ai/status/', views.status, name='ai-status'),
    path('ai/ask/', views.ask, name='ai-ask'),
    path('ai/roadmap/', views.roadmap, name='ai-roadmap'),
    path('profile/review/', views.resume_review, name='ai-review'),
    path('recommendations/', views.recommendations, name='ai-recs'),
    path('jobs/<path:job_id>/summary/', views.summary, name='ai-summary'),
    path('jobs/<path:job_id>/rewrite/', views.rewrite, name='ai-rewrite'),
    path('jobs/<path:job_id>/outreach/', views.outreach, name='ai-outreach'),
    path('jobs/<path:job_id>/interview/feedback/', views.interview_feedback, name='ai-feedback'),
    path('jobs/<path:job_id>/similar/', views.similar, name='ai-similar'),
]
