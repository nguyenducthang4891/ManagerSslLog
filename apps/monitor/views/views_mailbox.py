"""
apps/monitor/views/views_mailbox.py
-------------------------------------
View cho trang Giám sát thư đi/đến (log-mailbox-*) -- dạng bảng, theo
ĐÚNG khuôn views_audit.py:
    - Trang tổng quan (mailbox_list) + api_query_mailbox: tenant_id qua
      query string, CHỈ áp dụng cho superuser.
    - api_mailbox_log_detail (xem 1 document JSON đầy đủ): tenant_id qua
      PATH param, validate chặt non-superuser khớp đúng tenant của họ.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.core.exceptions import ValidationError

from apps.monitor.services.mailbox import (
    MailboxService, MAIL_DIRECTION_CHOICES, MAIL_STATUS_CHOICES,
)
from apps.tenants.models import Tenant
from .view_shared import (
    _parse_int, _resolve_tenant_from_request, _resolve_tenant_from_path,
)


@login_required
def mailbox_list(request):
    """Render trang danh sách giám sát thư đi/đến (dạng bảng)."""
    context = {
        "mail_direction_choices": MAIL_DIRECTION_CHOICES,
        "mail_status_choices": MAIL_STATUS_CHOICES,
    }

    if request.user.is_superuser:
        context['tenant_list'] = Tenant.objects.order_by('name')

    return render(request, 'monitor/mailbox.html', context)


@login_required
def api_query_mailbox(request):
    """
    API JSON cho bảng giám sát thư. Query params: hours|days,
    mail_direction, status, search_email (lọc theo from hoặc to),
    page, page_size (phân trang thật qua ES from/size),
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
    mail_direction = request.GET.get('mail_direction') or None
    status = request.GET.get('status') or None
    search_email = request.GET.get('search_email') or None
    page = _parse_int(request.GET.get('page'), default=1)
    page_size = _parse_int(request.GET.get('page_size'), default=50)

    try:
        data = MailboxService.query(
            user=request.user,
            tenant=tenant,
            hours=hours,
            days=days,
            mail_direction=mail_direction,
            status=status,
            search_email=search_email,
            page=page,
            page_size=page_size,
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_mailbox_log_detail(request, tenant_id, doc_id):
    """
    API lấy 1 document mailbox ĐẦY ĐỦ theo _id -- dùng cho modal "xem JSON
    chi tiết". tenant_id PHẢI khớp path -- validate giống api_audit_log_detail.
    """
    try:
        tenant = _resolve_tenant_from_path(request, tenant_id)
    except PermissionError as e:
        return JsonResponse({"error": str(e)}, status=403)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=404)

    doc = MailboxService.get_log_detail(user=request.user, doc_id=doc_id, tenant=tenant)

    if doc is None:
        return JsonResponse({"error": "Không tìm thấy bản ghi log chỉ định."}, status=404)

    return JsonResponse(doc)