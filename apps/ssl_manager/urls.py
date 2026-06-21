from django.urls import path
from apps.ssl_manager import views

urlpatterns = [
    # Template Views
    path('certificates/', views.cert_list_view, name='cert_list'),
    path('certificates/<int:cert_id>/', views.cert_detail_view, name='cert_detail'),

    # API Endpoints
    path('api/certificates/upload/', views.api_upload_cert, name='api_upload_cert'),
    path('api/certificates/<int:cert_id>/deploy/', views.api_trigger_deploy, name='api_trigger_deploy'),
    path('api/certificates/<int:cert_id>/log/', views.api_get_realtime_log, name='api_get_realtime_log'),
path('api/certificates/<int:cert_id>/history/', views.api_get_deploy_history, name='api_get_deploy_history'),
    path('api/certificates/history/<int:history_id>/detail/', views.api_get_deploy_history_detail, name='api_get_deploy_history_detail'),
]