"""
apps/monitor/views/views_audit.py
-------------------------------------
View cho trang Audit Log (nhật ký hành động quản trị Zimbra) -- dạng bảng,
không có trang "host detail" riêng (khác metric) vì audit không gắn cố
định với 1 host, xem chi tiết qua modal "log gốc" trên cùng trang bảng.

PATTERN BẢO MẬT: giữ NHẤT QUÁN với views_metric.py --
    - Trang tổng quan (audit_list) + api_query_audit: tenant_id qua query
      string, CHỈ áp dụng cho superuser (giống api_query_metric).
    - api_audit_log_detail (xem 1 document cụ thể): tenant_id qua PATH
      param, validate chặt non-superuser khớp đúng tenant của họ (giống
      api_host_logs) -- vì đây là endpoint "xem 1 bản ghi cụ thể", rủi ro
      đoán/dò ID cao hơn so với xem danh sách tổng quan.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.core.exceptions import ValidationError

from apps.monitor.services.audit import AuditService, ACTION_CATEGORY_CHOICES
from apps.tenants.models import Tenant
from .view_shared import (
    _parse_int, _resolve_tenant_from_request, _resolve_tenant_from_path,
)


@login_required
def audit_list(request):
    """Render trang danh sách audit log (dạng bảng)."""
    context = {
        "action_category_choices": ACTION_CATEGORY_CHOICES,
    }

    if request.user.is_superuser:
        context['tenant_list'] = Tenant.objects.order_by('name')

    return render(request, 'monitor/audit.html', context)


@login_required
def api_query_audit(request):
    """
    API JSON cho bảng audit log. Query params: hours|days, action_category,
    keyword (tìm theo admin_email/auth_email), page, page_size (phân trang
    thật qua ES from/size -- dùng cho cơ chế "tải thêm khi kéo scroll"),
    tenant_id (chỉ superuser).
    """
    tenant, allowed = _resolve_tenant_from_request(request)

    if request.user.is_superuser and not allowed:
        return JsonResponse({
            "total": 0, "items": [], "page": 1, "page_size": 50,
            "total_pages": 1, "elk_cluster": None,
        })

    hours = _parse_int(request.GET.get('hours'))
    days = _parse_int(request.GET.get('days'))
    action_category = request.GET.get('action_category') or None
    keyword = request.GET.get('keyword') or None
    page = _parse_int(request.GET.get('page'), default=1)
    page_size = _parse_int(request.GET.get('page_size'), default=50)

    try:
        data = AuditService.query(
            user=request.user,
            tenant=tenant,
            hours=hours,
            days=days,
            action_category=action_category,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_audit_log_detail(request, tenant_id, doc_id):
    """
    API lấy 1 document audit ĐẦY ĐỦ theo _id -- dùng cho modal "xem log
    gốc". tenant_id PHẢI khớp path -- validate giống api_host_logs.
    """
    try:
        tenant = _resolve_tenant_from_path(request, tenant_id)
    except PermissionError as e:
        return JsonResponse({"error": str(e)}, status=403)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=404)

    doc = AuditService.get_log_detail(user=request.user, doc_id=doc_id, tenant=tenant)

    if doc is None:
        return JsonResponse({"error": "Không tìm thấy bản ghi log chỉ định."}, status=404)

    return JsonResponse(doc)