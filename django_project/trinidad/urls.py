from django.urls import path
from . import views

urlpatterns = [
    path('local/', views.local_summary, name='local-summary'),
    path('local', views.local_summary, name='local-summary-no-slash'),
    path('local/employers/', views.employers, name='local-employers'),
    path('local/employers', views.employers, name='local-employers-no-slash'),
    path('sources/', views.sources, name='sources'),
    path('sources', views.sources, name='sources-no-slash'),
    path('sources/custom/', views.custom_sites, name='sources-custom'),
    path('sources/custom', views.custom_sites, name='sources-custom-no-slash'),
    path('sources/custom/test/', views.test_custom_site, name='sources-custom-test'),
    path('sources/detect/', views.detect_site, name='sources-detect'),
    path('sources/<str:name>/test/', views.test_source, name='source-test'),
    path('sources/<str:name>/test', views.test_source, name='source-test-no-slash'),
]
