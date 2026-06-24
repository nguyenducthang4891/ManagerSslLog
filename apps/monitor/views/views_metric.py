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
from .view_shared import (
    _parse_int, _resolve_tenant_from_request, _resolve_tenant_from_path,
)



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

    PHÂN TRANG ES THẬT: dùng MetricService.query_paginated() (KHÔNG phải
    query() -- vẫn giữ nguyên cho metric.html/api_query_metric, không ảnh
    hưởng gì) -- severity_filter được đẩy xuống thành range query ngay
    trong Elasticsearch (xem _apply_severity_filter trong services/metric.py),
    nên "total"/"total_pages" CHÍNH XÁC 100% và "from"/"size" phân trang
    đúng từng trang, không cần re-fetch lại từ đầu mỗi lần tải thêm (khác
    với cách "tăng page_size" tạm thời trước đây).
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
    page = _parse_int(request.GET.get('page'), default=1)
    page_size = _parse_int(request.GET.get('page_size'), default=50)

    try:
        data = MetricService.query_paginated(
            user=request.user,
            tenant=tenant,
            hours=hours,
            hostname=hostname.strip().lower(),  # chuẩn hoá lowercase, khớp .keyword exact-match trên ES
            severity_filter=severity,
            page=page,
            page_size=page_size,
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)