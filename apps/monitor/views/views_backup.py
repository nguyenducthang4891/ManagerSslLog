"""
apps/monitor/views/views_backup.py
-------------------------------------
View cho trang Giám sát Backup Mailbox (log-backup-*) -- dạng bảng, theo
ĐÚNG khuôn views_mailbox.py:
    - Trang tổng quan (backup_list) + api_query_backup: tenant_id qua
      query string, CHỈ áp dụng cho superuser.
    - api_backup_log_detail (xem 1 document JSON đầy đủ): tenant_id qua
      PATH param, validate chặt non-superuser khớp đúng tenant của họ.

THÊM RIÊNG (khác mailbox): api_backup_summary -- trả về thống kê tổng hợp
(số tài khoản đã backup thành công, tổng dung lượng...) cho khoảng thời
gian đã chọn, đúng mục đích ban đầu (xem theo ngày backup được bao nhiêu
tài khoản, tổng dung lượng bao nhiêu) -- xem BackupService.get_summary().
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.core.exceptions import ValidationError

from apps.monitor.services.backup import (
    BackupService, BACKUP_MODE_CHOICES, BACKUP_STATUS_CHOICES,
)
from apps.tenants.models import Tenant
from .view_shared import (
    _parse_int, _resolve_tenant_from_request, _resolve_tenant_from_path,
)


@login_required
def backup_list(request):
    """Render trang danh sách giám sát backup mailbox (dạng bảng)."""
    context = {
        "backup_mode_choices": BACKUP_MODE_CHOICES,
        "backup_status_choices": BACKUP_STATUS_CHOICES,
    }

    if request.user.is_superuser:
        context['tenant_list'] = Tenant.objects.order_by('name')

    return render(request, 'monitor/backup.html', context)


@login_required
def api_query_backup(request):
    """
    API JSON cho bảng giám sát backup. Query params: hours|days,
    backup_mode, status, search_account (lọc theo tên tài khoản),
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
    backup_mode = request.GET.get('backup_mode') or None
    status = request.GET.get('status') or None
    search_account = request.GET.get('search_account') or None
    page = _parse_int(request.GET.get('page'), default=1)
    page_size = _parse_int(request.GET.get('page_size'), default=50)

    try:
        data = BackupService.query(
            user=request.user,
            tenant=tenant,
            hours=hours,
            days=days,
            backup_mode=backup_mode,
            status=status,
            search_account=search_account,
            page=page,
            page_size=page_size,
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_backup_summary(request):
    """
    API thống kê tổng hợp (số tài khoản đã backup thành công, tổng dung
    lượng, số lượng theo trạng thái) cho khoảng thời gian đã chọn. Query
    params: hours|days, backup_mode, tenant_id (chỉ superuser) -- giống
    api_alert_summary của metric, KHÔNG có phân trang (luôn là 1 con số
    tổng hợp, không phải danh sách).
    """
    tenant, allowed = _resolve_tenant_from_request(request)

    if request.user.is_superuser and not allowed:
        return JsonResponse({
            "success_count": 0, "failed_count": 0, "no_content_count": 0,
            "unique_accounts_backed_up": 0, "total_size_bytes": 0, "elk_cluster": None,
        })

    hours = _parse_int(request.GET.get('hours'))
    days = _parse_int(request.GET.get('days'), default=1)  # mặc định thống kê "hôm nay" (1 ngày gần nhất)
    backup_mode = request.GET.get('backup_mode') or None

    try:
        data = BackupService.get_summary(
            user=request.user,
            tenant=tenant,
            hours=hours,
            days=days,
            backup_mode=backup_mode,
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def api_backup_log_detail(request, tenant_id, doc_id):
    """
    API lấy 1 document backup ĐẦY ĐỦ theo _id -- dùng cho modal xem JSON
    chi tiết. tenant_id PHẢI khớp path -- validate giống
    api_mailbox_log_detail.
    """
    try:
        tenant = _resolve_tenant_from_path(request, tenant_id)
    except PermissionError as e:
        return JsonResponse({"error": str(e)}, status=403)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=404)

    doc = BackupService.get_log_detail(user=request.user, doc_id=doc_id, tenant=tenant)

    if doc is None:
        return JsonResponse({"error": "Không tìm thấy bản ghi log chỉ định."}, status=404)

    return JsonResponse(doc)