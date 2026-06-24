from django.urls import path
from apps.monitor.views import views_metric, config, views_audit, views_mailbox

urlpatterns = [
    # Template Views (Giao diện hiển thị)
    path('', views_metric.metric, name='monitor_metric'),  # Trùng khớp với /monitor/
    path('config/', config.config_list_view, name='monitor_config_list'),  # Trùng khớp với /monitor/config/

    # Giao diện chi tiết lịch sử Log của riêng 1 Hostname.
    # THAY ĐỔI: thêm "tenant/<int:tenant_id>/" vào path -- bắt buộc phải có
    # tenant rõ ràng trong URL, để:
    #   1. Superuser biết đang xem log của tenant nào (trước đây thiếu hẳn,
    #      gây lỗi 400 vì api_host_logs cần tenant_id mà không có cách
    #      truyền vào từ link cũ).
    #   2. Non-superuser: tenant_id trong URL CHỈ mang tính hiển thị/định
    #      tuyến -- view vẫn PHẢI validate khớp với user.tenant_id thực tế,
    #      không tin tưởng giá trị trong URL (chống user tự sửa URL để xem
    #      tenant khác). Xem views_metric.host_detail_view().
    path('tenant/<int:tenant_id>/host/<str:hostname>/detail/',
         views_metric.host_detail_view, name='monitor_host_detail'),

    # API Endpoints phục vụ kéo dữ liệu từ cụm Elasticsearch
    path('api/metric/', views_metric.api_query_metric, name='api_query_metric'),
    path('api/summary/', views_metric.api_alert_summary, name='api_alert_summary'),

    # API chuyên trách trả về chuỗi lịch sử (Timeseries) của duy nhất 1 host.
    # THAY ĐỔI: thêm tenant_id vào path, đồng bộ với monitor_host_detail ở
    # trên -- tránh phải truyền qua query string (?tenant_id=...) dễ quên.
    path('api/tenant/<int:tenant_id>/host/logs/', views_metric.api_host_logs, name='api_host_logs'),

    # Cấu hình cụm ELK & Ngưỡng (Dành cho Superuser và Tenant Admin)
    path('api/elk-config/add/', config.api_add_elk_config, name='api_add_elk_config'),
    path('api/elk-config/<int:config_id>/edit/', config.api_edit_elk_config, name='api_edit_elk_config'),
    path('api/elk-config/<int:config_id>/delete/', config.api_delete_elk_config, name='api_delete_elk_config'),
    path('api/threshold/upsert/', config.api_upsert_threshold, name='api_upsert_threshold'),
    path('api/threshold/<int:threshold_id>/delete/', config.api_delete_threshold, name='api_delete_threshold'),
]

urlpatterns += [
    path('audit/', views_audit.audit_list, name='monitor_audit_list'),
    path('api/audit/', views_audit.api_query_audit, name='api_query_audit'),
    # Lấy 1 document audit đầy đủ theo _id -- dùng cho modal "xem log gốc".
    # tenant_id trong path giống pattern host_logs, validate quyền tương tự.
    path('api/tenant/<int:tenant_id>/audit/<str:doc_id>/',
         views_audit.api_audit_log_detail, name='api_audit_log_detail'),
]


urlpatterns += [
    path('mailbox/', views_mailbox.mailbox_list, name='monitor_mailbox_list'),
    path('api/mailbox/', views_mailbox.api_query_mailbox, name='api_query_mailbox'),
    # Lấy 1 document mailbox đầy đủ theo _id -- dùng cho modal JSON chi tiết.
    # tenant_id trong path giống pattern audit/host_logs, validate quyền tương tự.
    path('api/tenant/<int:tenant_id>/mailbox/<str:doc_id>/',
         views_mailbox.api_mailbox_log_detail, name='api_mailbox_log_detail'),
]