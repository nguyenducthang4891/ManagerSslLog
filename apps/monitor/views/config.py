from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from apps.monitor.services import ELKClusterConfigService, AlertThresholdService
from apps.monitor.models import AlertThreshold
from apps.tenants.models import Tenant


@login_required(login_url='login')
def config_list_view(request):
    """
    Trang quản trị cấu hình giám sát:
    - Superuser: thấy cả 2 phần (Cụm ELK + Ngưỡng cảnh báo của mọi tenant).
    - Tenant Admin: chỉ thấy phần Ngưỡng cảnh báo của tổ chức mình (không
      thấy/sửa được Cụm ELK -- đó là hạ tầng do Superadmin quản lý).
    """
    if not request.user.is_superuser and request.user.role != 'tenant_admin':
        return render(request, 'errors/403.html', {'error': 'Bạn không có quyền truy cập trang cấu hình giám sát.'})

    elk_configs = []
    if request.user.is_superuser:
        elk_configs = ELKClusterConfigService.get_list(request.user)

    thresholds = AlertThresholdService.get_list(request.user)
    tenants = Tenant.objects.all().order_by('name') if request.user.is_superuser else []

    return render(request, 'monitor/config.html', {
        'elk_configs': elk_configs,
        'thresholds': thresholds,
        'tenants': tenants,
        'metric_choices': AlertThreshold.METRIC_CHOICES,
    })


# ============================================================================
# API: ELKClusterConfig (chỉ superuser)
# ============================================================================
@login_required(login_url='login')
def api_add_elk_config(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        ELKClusterConfigService.create(
            user=request.user,
            name=request.POST.get('name', ''),
            hosts=request.POST.get('hosts', ''),
            is_default=request.POST.get('is_default') == 'true',
            tenant_id=int(request.POST.get('tenant_id')) if request.POST.get('tenant_id') else None,
            username=request.POST.get('username', ''),
            password=request.POST.get('password', ''),
        )
        return JsonResponse({'message': 'Đã thêm cấu hình cụm ELK thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_edit_elk_config(request, config_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        ELKClusterConfigService.update(
            user=request.user,
            config_id=config_id,
            name=request.POST.get('name'),
            hosts=request.POST.get('hosts'),
            username=request.POST.get('username'),
            password=request.POST.get('password'),
        )
        return JsonResponse({'message': 'Đã cập nhật cấu hình cụm ELK thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_delete_elk_config(request, config_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        ELKClusterConfigService.delete(request.user, config_id)
        return JsonResponse({'message': 'Đã xóa cấu hình cụm ELK thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


# ============================================================================
# API: AlertThreshold (superuser mọi tenant, tenant_admin chỉ tổ chức mình)
# ============================================================================
@login_required(login_url='login')
def api_upsert_threshold(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        warning = float(request.POST.get('warning_threshold'))
        critical = float(request.POST.get('critical_threshold'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Giá trị ngưỡng phải là số hợp lệ.'}, status=400)

    tenant_id = request.POST.get('tenant_id')
    try:
        AlertThresholdService.upsert(
            acting_user=request.user,
            metric=request.POST.get('metric', ''),
            warning_threshold=warning,
            critical_threshold=critical,
            tenant_id=int(tenant_id) if tenant_id else None,
        )
        return JsonResponse({'message': 'Đã lưu ngưỡng cảnh báo thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_delete_threshold(request, threshold_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        AlertThresholdService.delete(request.user, threshold_id)
        return JsonResponse({'message': 'Đã xóa ngưỡng cảnh báo, hệ thống sẽ dùng lại ngưỡng mặc định.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)