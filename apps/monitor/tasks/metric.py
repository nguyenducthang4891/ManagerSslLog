from celery import shared_task
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from apps.monitor.services import MetricService

User = get_user_model()


@shared_task
def broadcast_monitor_metrics():
    """
    Task chạy ngầm định kỳ (mỗi 3 giây) quét dữ liệu từ Elasticsearch
    và đẩy qua Channel Layer xuống Client đang kết nối WebSocket.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return "Channel layer chưa được cấu hình."

    # Lấy đại diện 1 tài khoản Superuser hoặc Admin hệ thống để bẻ khóa phân quyền
    # Vì Celery chạy ngầm ở Background không có HTTP request.user
    admin_user = User.objects.filter(is_superuser=True).first()
    if not admin_user:
        return "Không tìm thấy tài khoản admin hệ thống để thực hiện query."

    try:
        # Sử dụng đúng Service hiện tại của bạn để truy vấn Elasticsearch 24h qua
        data = MetricService.query(user=admin_user, hours=24)

        # Đồng bộ luồng Sync (Celery) sang Async (Channels WebSocket)
        async_to_sync(channel_layer.group_send)(
            "monitor_metrics_group",  # Tên group trùng vớiconsumers.py
            {
                "type": "send_metrics_update",  # Hàm xử lý trong consumers.py
                "data": data
            }
        )
        return "Đã cập nhật dữ liệu realtime tới các client thành công."
    except Exception as e:
        return f"Lỗi khi quét dữ liệu ELK: {str(e)}"