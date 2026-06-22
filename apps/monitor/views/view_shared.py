from django.core.exceptions import ValidationError

from apps.tenants.models import Tenant


def _parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_tenant_from_request(request):
    """
    Superuser: đọc tenant_id từ query string (?tenant_id=..). Không truyền
    -> trả về None (services/base.py sẽ raise lỗi rõ ràng nếu cố query mà
    không có tenant, vì non-superuser luôn bắt buộc có scope -- còn
    superuser không truyền tenant nghĩa là "xem tất cả", nên ở layer VIEW
    này ta chủ động CHẶN sớm, không gọi MetricService nếu superuser chưa
    chọn tenant, để tránh kéo toàn bộ dữ liệu ngoài ý muốn).

    Non-superuser: luôn trả về None ở đây -- get_effective_tenant() trong
    services/base.py sẽ tự ép về user.tenant, không cần resolve ở view.
    """
    if not request.user.is_superuser:
        return None, True  # (tenant, allowed_to_query)

    tenant_id = _parse_int(request.GET.get('tenant_id'))
    if not tenant_id:
        return None, False  # Superuser chưa chọn tenant -- không cho query.

    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        return None, False

    return tenant, True


def _resolve_tenant_from_path(request, tenant_id: int):
    """
    Dùng cho các view có tenant_id NẰM TRONG URL PATH (host_detail_view,
    api_host_logs) -- khác với _resolve_tenant_from_request() (query string,
    chỉ áp dụng cho superuser).

    QUY TẮC BẢO MẬT QUAN TRỌNG: tenant_id trong URL KHÔNG được tin tưởng
    tuyệt đối với non-superuser -- một user có thể tự sửa URL
    (/monitor/tenant/<id>/host/...) để thử xem dữ liệu của tenant khác.
    Vì vậy:
        - Non-superuser: bắt buộc tenant_id trong path PHẢI khớp đúng
          user.tenant_id của chính họ. Sai -> raise PermissionError (view
          gọi hàm này phải catch và trả 403).
        - Superuser: tenant_id trong path là tenant họ ĐANG chọn xem (từ
          dropdown ở trang tổng quan) -- chỉ cần validate tenant đó có tồn
          tại trong hệ thống.

    Trả về: Tenant instance (luôn hợp lệ nếu không raise exception).
    """
    if not request.user.is_superuser:
        if request.user.tenant_id != tenant_id:
            raise PermissionError("Bạn không có quyền xem dữ liệu của tổ chức khác.")
        try:
            return Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise PermissionError("Tổ chức của bạn không tồn tại hoặc đã bị xóa.")

    try:
        return Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        raise ValidationError("Tổ chức (tenant) chỉ định không tồn tại.")