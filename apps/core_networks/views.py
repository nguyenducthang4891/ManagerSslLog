from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from apps.core_networks.models import ZimbraServer, Domain
from apps.core_networks.services import ZimbraServerService, DomainService
from apps.core_networks.zimbra_soap import ZimbraAdminSoapClient
from apps.tenants.models import Tenant


@login_required(login_url='login')
def server_list_view(request):
    servers = ZimbraServerService.get_list(request.user)
    return render(request, 'networks/server_list.html', {'servers': servers})


@login_required(login_url='login')
def domain_list_view(request):
    domains = DomainService.get_list(request.user)
    servers = ZimbraServerService.get_list(request.user)

    tenants = Tenant.objects.all().order_by('name') if request.user.is_superuser else []

    context = {
        'domains': domains,
        'servers': servers,
        'tenants': tenants,
    }

    return render(request, 'networks/domain_list.html', context)


# --- API FBV ENDPOINTS ---
@login_required(login_url='login')
def api_add_server(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Chỉ có Superadmin mới có quyền thêm hạ tầng.'}, status=403)

    try:
        ZimbraServerService.add_server(
            name=request.POST.get('name'),
            hostname=request.POST.get('hostname'),
            port=int(request.POST.get('port', 22)),
            username=request.POST.get('username'),
            password=request.POST.get('password', ''),
            zimbra_admin_email=request.POST.get('srv_admin_email'),
            zimbra_admin_password=request.POST.get('zimbra_admin_password')
        )
        return JsonResponse({'message': 'Thêm máy chủ hạ tầng thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_edit_server(request, server_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Chỉ có Superadmin mới có quyền chỉnh sửa hạ tầng.'}, status=403)

    try:
        # FIX: dùng service với allowed_fields + bỏ giá trị rỗng, thay vì set trực tiếp
        # từng field trên instance (tránh việc ghi đè zimbra_admin_email thành rỗng).
        ZimbraServerService.update_server(
            server_id=server_id,
            name=request.POST.get('name'),
            hostname=request.POST.get('hostname'),
            port=int(request.POST.get('port')) if request.POST.get('port') else None,
            username=request.POST.get('username'),
            ssh_password=request.POST.get('password') or None,
            zimbra_admin_email=request.POST.get('srv_admin_email') or None,
            zimbra_admin_password=request.POST.get('zimbra_admin_password') or None,
        )
        return JsonResponse({'message': 'Cập nhật thông tin máy chủ thành công!'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required(login_url='login')
def api_test_soap_connection(request, server_id):
    """API test kết nối ứng dụng Zimbra SOAP qua port 7071"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        server = ZimbraServer.objects.get(id=server_id)
        client = ZimbraAdminSoapClient(server)
        client.login()
        return JsonResponse({'success': True, 'message': 'Kết nối API Zimbra SOAP (Port 7071) thành công!'})
    except ZimbraServer.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Không tìm thấy máy chủ.'}, status=404)
    except ValidationError as e:
        return JsonResponse({'success': False, 'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': f"Lỗi kết nối SOAP: {str(e)}"}, status=400)


# Trong views.py
@login_required(login_url='login')
def api_add_domain(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    if not request.user.tenant and not request.user.is_superuser:
        return JsonResponse({'error': 'Tài khoản không hợp lệ.'}, status=403)

    # LẤY GIÁ TRỊ CHECKBOX: Nếu có truyền lên bất kỳ giá trị nào (ví dụ 'on' hoặc 'true') -> True, ngược lại -> False
    create_on_zimbra = request.POST.get('create_on_zimbra') is not None

    try:
        DomainService.add_domain(
            tenant=request.user.tenant,
            domain_name=request.POST.get('name'),
            server_id=int(request.POST.get('server_id')),
            is_superuser=request.user.is_superuser,
            create_on_zimbra=create_on_zimbra  # Truyền biến này vào service
        )
        return JsonResponse({'message': 'Đăng ký tên miền thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_edit_domain(request, domain_id):
    """
    FIX: trước đây hàm này chỉ đổi con trỏ domain.server trong DB, không đồng bộ
    gì với Zimbra thật. Giờ gọi DomainService.change_domain_server để tự động
    tạo domain trên Zimbra server mới nếu chưa tồn tại ở đó.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        new_server_id = int(request.POST.get('server_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Server chỉ định không hợp lệ.'}, status=400)

    try:
        DomainService.change_domain_server(request.user, domain_id, new_server_id)
        return JsonResponse({'message': 'Chuyển đổi cụm Mail Server quản lý Domain thành công!'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_change_domain_status(request, domain_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    is_active = request.POST.get('is_active') == 'true'
    try:
        DomainService.change_domain_status(request.user, domain_id, is_active)
        return JsonResponse({'message': 'Cập nhật trạng thái tên miền thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_delete_domain(request, domain_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        # FIX: truyền request.user (không phải request.user.tenant) để service
        # tự xử lý nhánh superuser đúng cách.
        DomainService.delete_domain(request.user, domain_id)
        return JsonResponse({'message': 'Xóa tên miền thành công.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_assign_domain_tenant(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if not request.user.is_superuser:
        return JsonResponse({'error': 'Bạn không có đặc quyền điều phối tài nguyên hệ thống.'}, status=403)

    domain_id = request.POST.get('domain_id')
    tenant_id = request.POST.get('tenant_id')

    try:
        domain = Domain.objects.get(id=domain_id)

        if tenant_id:
            tenant = Tenant.objects.get(id=tenant_id)
            domain.tenant = tenant
            domain.save(update_fields=['tenant'])
            return JsonResponse(
                {'message': f'Đã bàn giao quyền sở hữu domain {domain.name} cho tổ chức {tenant.name}.'})
        else:
            old_tenant_name = domain.tenant.name if domain.tenant else "Tự do"
            domain.tenant = None
            domain.save(update_fields=['tenant'])
            return JsonResponse({
                'message': f'Đã gỡ domain {domain.name} khỏi tổ chức {old_tenant_name}. Domain hiện đang ở trạng thái tự do.'})

    except Domain.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy thông tin Domain chỉ định.'}, status=404)
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy tổ chức chỉ định.'}, status=404)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi hệ thống: {str(e)}'}, status=500)


@login_required(login_url='login')
def api_test_server_connection(request, server_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if not request.user.is_superuser:
        return JsonResponse({'error': 'Bạn không có quyền thực hiện kiểm tra hạ tầng vật lý.'}, status=403)

    success, message = ZimbraServerService.test_ssh_connection(server_id)

    if success:
        return JsonResponse({'success': True, 'message': message})
    else:
        return JsonResponse({'success': False, 'error': message}, status=400)