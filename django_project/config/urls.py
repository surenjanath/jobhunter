from django.contrib import admin
from django.urls import path, include
from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    # pages — each has its own URL and template (templates/pages/)
    path('', core_views.home, name='page-home'),
    path('ledger/', core_views.ledger, name='page-ledger'),
    path('pipeline/', core_views.pipeline, name='page-pipeline'),
    path('analytics/', core_views.analytics_page, name='page-analytics'),
    path('profile/', core_views.profile_page, name='page-profile'),
    path('trinidad/', core_views.trinidad_page, name='page-trinidad'),
    path('settings/', core_views.settings_page, name='page-settings'),
    path('health/', core_views.health, name='health'),
    path('health', core_views.health, name='health-no-slash'),
    path('api/settings/', core_views.settings_view, name='settings'),
    path('api/settings', core_views.settings_view, name='settings-no-slash'),
    path('api/activity/', core_views.activity, name='activity'),
    path('api/activity', core_views.activity, name='activity-no-slash'),
    path('api/', include('ai.urls')),          # also before jobs (see note below)
    path('api/', include('accounts.urls')),
    path('api/', include('candidate.urls')),   # before jobs: /jobs/<id>/match/ must win over the greedy /jobs/<path>/
    path('api/', include('jobs.urls')),
    path('api/', include('analytics.urls')),
    path('api/', include('letters.urls')),
    path('api/', include('trinidad.urls')),
]
