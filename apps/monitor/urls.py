from django.urls import path
from apps.monitor.views import views_metric, config

urlpatterns = [
    # Template Views (Giao diện hiển thị)
    path('', views_metric.metric, name='monitor_metric'),  # Trùng khớp với /monitor/
    path('config/', config.config_list_view, name='monitor_config_list'),  # Trùng khớp với /monitor/config/

    # Giao diện chi tiết lịch sử Log của riêng 1 Hostname
    path('host/<str:hostname>/detail/', views_metric.host_detail_view, name='monitor_host_detail'),

    # API Endpoints phục vụ kéo dữ liệu từ cụm Elasticsearch
    path('api/metric/', views_metric.api_query_metric, name='api_query_metric'),
    path('api/summary/', views_metric.api_alert_summary, name='api_alert_summary'),

    # API chuyên trách trả về chuỗi lịch sử (Timeseries) của duy nhất 1 host
    path('api/host/logs/', views_metric.api_host_logs, name='api_host_logs'),

    # Cấu hình cụm ELK & Ngưỡng (Dành cho Superuser và Tenant Admin)
    path('api/elk-config/add/', config.api_add_elk_config, name='api_add_elk_config'),
    path('api/elk-config/<int:config_id>/edit/', config.api_edit_elk_config, name='api_edit_elk_config'),
    path('api/elk-config/<int:config_id>/delete/', config.api_delete_elk_config, name='api_delete_elk_config'),
    path('api/threshold/upsert/', config.api_upsert_threshold, name='api_upsert_threshold'),
    path('api/threshold/<int:threshold_id>/delete/', config.api_delete_threshold, name='api_delete_threshold'),
]