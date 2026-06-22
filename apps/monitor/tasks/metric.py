from celery import shared_task
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from apps.monitor.services import MetricService
from apps.monitor.models import ELKClusterConfig
from apps.tenants.models import Tenant

User = get_user_model()


def _send_to_tenant_group(channel_layer, tenant_id, data):
    async_to_sync(channel_layer.group_send)(
        f"group_monitor_metrics_tenant_{tenant_id}",
        {"type": "send_metrics", "data": data},
    )


@shared_task
def broadcast_monitor_metrics():
    """
    Task chạy ngầm định kỳ (mỗi 3 giây) quét dữ liệu từ Elasticsearch và đẩy
    qua Channel Layer xuống Client đang kết nối WebSocket.

    BẢO MẬT (đã sửa so với bản gốc):
    - Bản gốc: query 1 LẦN với admin_user (superuser) KHÔNG truyền tenant
      -> base_filter() không lọc tenant_code -> kéo dữ liệu TẤT CẢ tenant,
      rồi gửi nguyên block đó vào 1 group DUY NHẤT mà mọi client (mọi
      tenant) đều join -> rò rỉ dữ liệu cross-tenant.
    - Bản sửa: lặp qua TỪNG tenant đang có cấu hình ELK (dùng chung hoặc
      riêng), query RIÊNG cho từng tenant, rồi gửi vào ĐÚNG group của
      tenant đó (group_monitor_metrics_tenant_<id>). Client chỉ nhận được
      dữ liệu của tenant mà chính họ đã subscribe (xem consumers.py).

    HIỆU NĂNG: nếu hệ thống có nhiều tenant, việc quét tuần tự từng tenant
    mỗi 3s có thể chậm dần khi số tenant tăng. Nếu cần, có thể tách thành
    nhiều task con (1 task / tenant) chạy song song qua Celery group, hoặc
    tăng khoảng nghỉ giữa các lượt quét. Hiện tại giữ tuần tự cho đơn giản
    và dễ kiểm soát lỗi từng tenant độc lập (1 tenant lỗi không chặn các
    tenant khác, nhờ try/except trong từng vòng lặp).
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return "Channel layer chưa được cấu hình."

    try:
        # Lấy đại diện 1 tài khoản Superuser để bẻ khóa phân quyền khi query
        # (Celery chạy ngầm ở Background, không có HTTP request.user).
        admin_user = User.objects.filter(is_superuser=True).first()
    except Exception as e:
        return f"Lỗi khi truy vấn tài khoản admin hệ thống: {str(e)}"

    if not admin_user:
        return "Không tìm thấy tài khoản Superuser nào để thực hiện query nền."

    results = []

    # Danh sách tenant cần quét: ưu tiên tenant có cấu hình ELK riêng, cộng
    # thêm các tenant KHÔNG có cấu hình riêng (sẽ rơi về cụm is_default).
    tenant_ids_with_dedicated_elk = set(
        ELKClusterConfig.objects.filter(tenant__isnull=False).values_list('tenant_id', flat=True)
    )
    all_tenant_ids = set(Tenant.objects.values_list('id', flat=True))

    if not all_tenant_ids:
        return "Hệ thống chưa có Tenant nào để quét dữ liệu giám sát."

    for tenant_id in all_tenant_ids:
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            data = MetricService.query(user=admin_user, tenant=tenant, hours=24)
            _send_to_tenant_group(channel_layer, tenant_id, data)
            results.append(f"OK:{tenant_id}")
        except Exception as e:
            # Lỗi của 1 tenant (ví dụ ELK host của riêng họ bị sập) KHÔNG
            # được làm crash toàn bộ task, để các tenant khác vẫn nhận data.
            results.append(f"FAIL:{tenant_id}:{str(e)}")

    return "Đã quét xong {} tenant. Chi tiết: {}".format(len(all_tenant_ids), "; ".join(results))