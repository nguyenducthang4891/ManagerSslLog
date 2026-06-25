from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from apps.ssl_manager.services import SSLLifecycleService
from apps.ssl_manager.models import SSLCertificate, DeployHistory
from apps.ssl_manager.services import ZimbraDeployService
from apps.core_networks.services import DomainService
import threading

from apps.ssl_manager.services.ssl_checker import SSLCheckService


@login_required(login_url='login')
def cert_list_view(request):
    certs = SSLLifecycleService.get_list(request.user)
    domains = DomainService.get_list(request.user)
    return render(request, 'ssl/cert_list.html', {'certs': certs, 'domains': domains})


@login_required(login_url='login')
# apps/ssl_manager/views.py

@login_required(login_url='login')
def cert_detail_view(request, cert_id):
    try:
        cert = SSLLifecycleService.get_detail(request.user, cert_id)
        history = cert.deploy_history.select_related('triggered_by')[:10]
        # BỔ SUNG: Lấy danh sách domain để phục vụ modal update thông tin
        domains = DomainService.get_list(request.user)

        return render(request, 'ssl/cert_detail.html', {
            'cert': cert,
            'deploy_history': history,
            'domains': domains  # Truyền sang template
        })
    except ValidationError as e:
        return render(request, 'errors/403.html', {'error': e.message}, status=403)


# --- API FBV ENDPOINTS ---
@login_required(login_url='login')
def api_upload_cert(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        SSLLifecycleService.upload_and_create_certificate(
            user=request.user,
            domain_id=int(request.POST.get('domain_id')),
            name=request.POST.get('name'),
            root_file=request.FILES.get('root_cert'),
            inter_file=request.FILES.get('inter_cert'),
            server_file=request.FILES.get('server_cert'),
            key_file=request.FILES.get('private_key')
        )
        return JsonResponse({'message': 'Tải lên và xác thực chứng chỉ thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_trigger_deploy(request, cert_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Validate đồng bộ ngay tại view (trả lỗi 400/403 ngay nếu sai), CHỈ phần
    # thực sự cần SSH lâu mới chạy trong thread.
    try:
        cert = SSLLifecycleService.get_detail(request.user, cert_id)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=403)

    if cert.status in [SSLCertificate.STATUS_INVALID, SSLCertificate.STATUS_DEPLOYING]:
        return JsonResponse(
            {'error': 'Trạng thái chứng chỉ hiện tại không khả dụng để triển khai.'}, status=400
        )

    # MỚI: truyền request.user để ZimbraDeployService ghi nhận "ai" kích hoạt
    # lần deploy này vào DeployHistory.triggered_by.
    deploy_service = ZimbraDeployService(cert_id=cert.id, triggered_by=request.user)
    t = threading.Thread(target=deploy_service.execute_deploy)
    t.daemon = True
    t.start()

    return JsonResponse({'message': 'Tiến trình deploy đã được kích hoạt chạy ngầm.'})


def api_get_realtime_log(request, cert_id):
    try:
        cert = SSLLifecycleService.get_detail(request.user, cert_id)
        return JsonResponse({
            'status': cert.status,
            'status_display': cert.get_status_display(),  # ✅ THÊM DÒNG NÀY
            'deploy_log': cert.deploy_log or 'Đang khởi tạo kết nối SSH...'
        })
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=403)


@login_required(login_url='login')
def api_get_deploy_history(request, cert_id):
    """
    MỚI: trả về danh sách lịch sử các lần deploy của 1 cert, dùng để load lại
    bảng lịch sử bằng AJAX sau khi 1 lần deploy mới vừa hoàn tất (không cần
    reload cả trang).
    """
    try:
        cert = SSLLifecycleService.get_detail(request.user, cert_id)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=403)

    history = cert.deploy_history.select_related('triggered_by')[:20]
    return JsonResponse({
        'history': [
            {
                'id': h.id,
                'status': h.status,
                'status_display': h.get_status_display(),
                'triggered_by': h.triggered_by.email if h.triggered_by else 'Hệ thống',
                'started_at': h.started_at.strftime('%Y-%m-%d %H:%M:%S'),
                'finished_at': h.finished_at.strftime('%Y-%m-%d %H:%M:%S') if h.finished_at else None,
                'duration_seconds': h.duration_seconds,
            }
            for h in history
        ]
    })


@login_required(login_url='login')
def api_get_deploy_history_detail(request, history_id):
    """MỚI: trả về log_snapshot đầy đủ của 1 lần deploy cụ thể trong lịch sử."""
    try:
        history = DeployHistory.objects.select_related('certificate').get(id=history_id)
        # Kiểm tra quyền truy cập qua cert (tái dùng logic phân quyền sẵn có).
        SSLLifecycleService.get_detail(request.user, history.certificate_id)
    except DeployHistory.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy lịch sử deploy.'}, status=404)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=403)

    return JsonResponse({
        'log_snapshot': history.log_snapshot,
        'status': history.status,
    })


@login_required(login_url='login')
def api_update_cert(request, cert_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        # ✅ Validate quyền trước, trước khi nhận files
        cert = SSLLifecycleService.get_detail(request.user, cert_id)

        # Giờ mới nhận files nếu quyền ok
        SSLLifecycleService.update_certificate(
            user=request.user,
            cert_id=cert_id,
            domain_id=int(request.POST.get('domain_id')),
            root_file=request.FILES.get('root_cert'),
            inter_file=request.FILES.get('inter_cert'),
            server_file=request.FILES.get('server_cert'),
            key_file=request.FILES.get('private_key')
        )
        return JsonResponse({'message': 'Cập nhật thông tin chứng chỉ thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_delete_cert(request, cert_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        SSLLifecycleService.delete_certificate(request.user, cert_id)
        return JsonResponse({'message': 'Xóa chứng chỉ thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_check_ssl_live(request, cert_id):
    """API Check trực tiếp trạng thái cài đặt SSL thực tế của Domain"""
    try:
        cert = SSLLifecycleService.get_detail(request.user, cert_id)
        # Thực hiện kiểm tra live kết nối tới domain.name
        result = SSLCheckService.check_live_ssl(cert.domain.name)
        return JsonResponse(result)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=403)