"""
apps/monitor/views/views_metric.py
-------------------------------------
LƯU Ý: File này được viết lại dựa trên suy luận từ urls.py, MetricService và
các template (metric.html, metric_detail.html) -- vì file gốc không có trong
bộ tài liệu được cung cấp. Vui lòng đối chiếu với file thật của bạn, đặc biệt:
    - decorator phân quyền đang dùng (@login_required, middleware riêng,...)
    - cách lấy danh sách Tenant cho dropdown (nếu đã có sẵn ở nơi khác)
    - format JSON response hiện tại của api_query_metric/api_host_logs
      (đổi tên field có thể ảnh hưởng tới monitor_metric.js phía client)

THAY ĐỔI CHÍNH so với hành vi gốc suy luận được:
    1. Superuser xem trang metric -> KHÔNG tự động query MetricService (vì
       không truyền tenant -> base_filter() bỏ qua filter tenant_code ->
       kéo dữ liệu TẤT CẢ tenant). Thay vào đó, superuser phải chọn tenant
       qua dropdown (tenant_list được truyền vào context), trang chỉ render
       khung rỗng + danh sách tenant.
    2. api_query_metric / api_alert_summary: nhận thêm query param
       `tenant_id` -- CHỈ áp dụng khi user.is_superuser; non-superuser luôn
       bị ép theo user.tenant (giữ đúng nguyên tắc cô lập đã có ở
       services/base.py:get_effective_tenant).
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.core.exceptions import ValidationError

from apps.monitor.services import MetricService
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


@login_required
def metric(request):
    """Render trang giám sát tổng quan (metric.html)."""
    context = {}

    if request.user.is_superuser:
        # Superuser: KHÔNG tự query summary mặc định (tránh kéo toàn bộ
        # tenant). Chỉ truyền danh sách tenant để render dropdown chọn.
        context['tenant_list'] = Tenant.objects.order_by('name')
        context['summary'] = {}
    else:
        try:
            context['summary'] = MetricService.get_alert_summary(user=request.user, hours=24)
        except ValidationError as e:
            context['summary'] = {}
            context['error'] = str(e)

    return render(request, 'monitor/metric.html', context)


@login_required
def host_detail_view(request, tenant_id, hostname):
    """
    Render trang chi tiết log của 1 host cụ thể (metric_detail.html).

    THAY ĐỔI: tenant_id giờ là path param bắt buộc (xem urls.py). Validate
    quyền truy cập NGAY TẠI VIEW này -- non-superuser cố sửa URL để xem
    tenant khác sẽ bị chặn với 403, không lộ bất kỳ dữ liệu nào.
    """
    try:
        tenant = _resolve_tenant_from_path(request, tenant_id)
    except PermissionError as e:
        return render(request, '403.html', {"message": str(e)}, status=403)
    except ValidationError as e:
        return render(request, '404.html', {"message": str(e)}, status=404)

    return render(request, 'monitor/metric_detail.html', {
        'hostname': hostname,
        'tenant_id': tenant.id,
        'tenant_name': tenant.name,
    })


@login_required
def api_query_metric(request):
    """
    API JSON cho Grid/Table view + WebSocket polling fallback.
    Query params: hours|days, severity, hostname, tenant_id (chỉ superuser).
    """
    tenant, allowed = _resolve_tenant_from_request(request)

    if request.user.is_superuser and not allowed:
        # Superuser chưa chọn tenant -- trả danh sách rỗng, KHÔNG lỗi 500,
        # để UI hiển thị placeholder "vui lòng chọn tổ chức" một cách êm.
        return JsonResponse({"total": 0, "items": [], "thresholds": {}, "elk_cluster": None})

    hours = _parse_int(request.GET.get('hours'))
    days = _parse_int(request.GET.get('days'))
    severity = request.GET.get('severity') or None
    hostname = request.GET.get('hostname') or None

    try:
        data = MetricService.query(
            user=request.user,
            tenant=tenant,
            hours=hours,
            days=days,
            severity_filter=severity,
            hostname=hostname,
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_alert_summary(request):
    tenant, allowed = _resolve_tenant_from_request(request)

    if request.user.is_superuser and not allowed:
        return JsonResponse({"total_samples": 0, "warning_count": 0, "critical_count": 0, "elk_cluster": None})

    hours = _parse_int(request.GET.get('hours'), default=24)

    try:
        data = MetricService.get_alert_summary(user=request.user, tenant=tenant, hours=hours)
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_host_logs(request, tenant_id):
    """
    API lấy lịch sử (timeseries) của DUY NHẤT 1 hostname -- dùng cho
    metric_detail.html. hostname là bắt buộc (query string).

    THAY ĐỔI: tenant_id giờ là path param bắt buộc (xem urls.py), validate
    quyền giống host_detail_view -- không còn dựa vào ?tenant_id= dễ quên
    hoặc bị sửa tùy ý qua query string.
    """
    hostname = request.GET.get('hostname')
    if not hostname:
        return JsonResponse({"error": "Thiếu tham số hostname."}, status=400)

    try:
        tenant = _resolve_tenant_from_path(request, tenant_id)
    except PermissionError as e:
        return JsonResponse({"error": str(e)}, status=403)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=404)

    hours = _parse_int(request.GET.get('hours'), default=24)
    severity = request.GET.get('severity') or None

    try:
        data = MetricService.query(
            user=request.user,
            tenant=tenant,
            hours=hours,
            hostname=hostname.strip().lower(),  # chuẩn hoá lowercase, khớp .keyword exact-match trên ES
            severity_filter=severity,
            page_size=1000,  # lịch sử 1 host cần nhiều record hơn trang tổng quan
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)