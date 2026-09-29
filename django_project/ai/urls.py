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
    path('jobs/<path:job_id>/interview/questions/', views.interview_questions, name='ai-interview-questions'),
    path('jobs/<path:job_id>/interview/feedback/', views.interview_feedback, name='ai-feedback'),
    path('ai/interview/summary/', views.interview_summary, name='ai-interview-summary'),
    path('ai/interview/sessions/', views.interview_sessions, name='ai-interview-sessions'),
    path('ai/interview/sessions/<int:sid>/', views.interview_session, name='ai-interview-session'),
    path('jobs/<path:job_id>/similar/', views.similar, name='ai-similar'),
    path('ai/voice/status/', views.voice_status, name='ai-voice-status'),
    path('ai/voice/speak/', views.speak, name='ai-voice-speak'),
]
