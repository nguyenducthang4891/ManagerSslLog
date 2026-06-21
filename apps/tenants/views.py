from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from apps.tenants.models import Tenant
from apps.tenants.services import AuthService, TenantUserService, TenantService
from django.contrib.auth import get_user_model

User = get_user_model()


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    error_msg = None
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        try:
            AuthService.authenticate_and_login(request, email, password)
            return redirect('dashboard')
        except ValidationError as e:
            error_msg = e.message

    return render(request, 'tenants/login.html', {'error': error_msg})


def logout_action(request):
    AuthService.logout_user(request)
    return redirect('login')


@login_required(login_url='login')
def dashboard_view(request):
    return render(request, 'dashboard.html')


@login_required(login_url='login')
def user_list_view(request):
    # FIX: bản gốc gọi service nhưng template dùng biến tên 'users' -- nếu service
    # trả về key khác tên thì danh sách sẽ luôn trống trên giao diện. Đảm bảo
    # context key khớp với những gì user_list.html sử dụng ({% for u in users %}).
    users = TenantUserService.get_list(request.user)
    return render(request, 'tenants/user_list.html', {'users': users})


# --- API FBV ENDPOINTS ---
@login_required(login_url='login')
def api_create_staff(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if not request.user.is_superuser and request.user.role != 'tenant_admin':
        return JsonResponse({'error': 'Bạn không có quyền thực hiện thao tác này.'}, status=403)

    email = request.POST.get('email')
    password = request.POST.get('password')
    full_name = request.POST.get('full_name', '')

    try:
        user = TenantUserService.create_staff(request.user.tenant, email, password, full_name)
        return JsonResponse({'message': 'Tạo nhân viên thành công', 'user_id': user.id})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_change_user_status(request, user_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if not request.user.is_superuser and request.user.role != 'tenant_admin':
        return JsonResponse({'error': 'Permission denied'}, status=403)

    is_active = request.POST.get('is_active') == 'true'
    try:
        TenantUserService.change_user_status(request.user.tenant, user_id, is_active)
        return JsonResponse({'message': 'Cập nhật trạng thái thành công'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_change_user_role(request, user_id):
    """
    MỚI: Cho phép Tenant Admin (hoặc Superuser) đổi vai trò nhân viên ngay tại
    user_list.html -- không cần qua thao tác "Gán Admin" ở tenant_list.html
    (vốn chỉ dành cho Superuser và chỉ có chiều nâng quyền, không hạ được).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    new_role = request.POST.get('role')
    try:
        target_user = TenantUserService.change_user_role(request.user, user_id, new_role)
        return JsonResponse({
            'message': f'Đã cập nhật vai trò của {target_user.email} thành {target_user.get_role_display()}.',
            'role': target_user.role,
        })
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def tenant_list(request):
    """Hiển thị trang quản trị danh sách tổ chức (Chỉ dành cho Superadmin)"""
    if not request.user.is_superuser:
        return render(request, 'errors/403.html', {'error': 'Chỉ có nhà phát triển hệ thống mới được vào phân hệ này.'})

    tenants = Tenant.objects.all().order_by('-created_at')
    unassigned_users = User.objects.filter(is_superuser=False).select_related('tenant')

    return render(request, 'tenants/tenant_list.html', {
        'tenants': tenants,
        'unassigned_users': unassigned_users
    })


@login_required(login_url='login')
def api_add_tenant(request):
    if request.method != 'POST' or not request.user.is_superuser:
        return JsonResponse({'error': 'Từ chối truy cập'}, status=403)

    name = request.POST.get('name', '').strip()
    code = request.POST.get('code', '').strip().upper()

    if not name or not code:
        return JsonResponse({'error': 'Tên và mã định danh tổ chức là bắt buộc.'}, status=400)

    if Tenant.objects.filter(code=code).exists():
        return JsonResponse({'error': 'Mã định danh tổ chức này đã tồn tại.'}, status=400)

    tenant = Tenant.objects.create(name=name, code=code)
    return JsonResponse({'message': f"Đã khởi tạo thành công không gian làm việc cho {tenant.name}."})


@login_required(login_url='login')
def api_edit_tenant(request, tenant_id):
    if request.method != 'POST' or not request.user.is_superuser:
        return JsonResponse({'error': 'Từ chối truy cập'}, status=403)

    try:
        tenant = Tenant.objects.get(id=tenant_id)
        tenant.name = request.POST.get('name', '').strip()
        tenant.is_active = request.POST.get('is_active') == 'true'
        tenant.save(update_fields=['name', 'is_active'])
        return JsonResponse({'message': 'Cập nhật thông tin Tenant thành công.'})
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy tổ chức.'}, status=404)


@login_required(login_url='login')
def api_delete_tenant(request, tenant_id):
    if request.method != 'POST' or not request.user.is_superuser:
        return JsonResponse({'error': 'Từ chối truy cập'}, status=403)

    try:
        tenant = Tenant.objects.get(id=tenant_id)
        if tenant.domains.exists():
            return JsonResponse({'error': 'Không thể xóa! Tổ chức này đang ràng buộc với hạ tầng Domain.'}, status=400)
        tenant.delete()
        return JsonResponse({'message': 'Đã xóa dữ liệu Tenant khỏi hệ thống.'})
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy dữ liệu.'}, status=404)


@login_required(login_url='login')
def api_assign_tenant_admin(request):
    """
    Đặc quyền điều phối: Đưa User vào Tenant và nâng cấp thành tenant_admin.
    FIX: trước đây hàm này gán role='tenant_admin' một cách vô điều kiện, không
    cảnh báo nếu user đã thuộc về một tenant khác (sẽ bị "rút" khỏi tổ chức cũ
    một cách âm thầm, không có dấu hiệu gì trên UI). Giờ trả về cảnh báo rõ
    trong message để Superuser biết chuyện gì đang xảy ra.
    """
    if request.method != 'POST' or not request.user.is_superuser:
        return JsonResponse({'error': 'Từ chối truy cập'}, status=403)

    user_id = request.POST.get('user_id')
    tenant_id = request.POST.get('tenant_id')

    try:
        user = User.objects.get(id=user_id)
        tenant = Tenant.objects.get(id=tenant_id)

        warning = ""
        if user.tenant_id and user.tenant_id != tenant.id:
            warning = f" (Lưu ý: tài khoản này đã được rút khỏi tổ chức cũ '{user.tenant.name}'.)"

        user.tenant = tenant
        user.role = 'tenant_admin'
        user.save(update_fields=['tenant', 'role'])

        return JsonResponse({
            'message': f"Đã chỉ định quyền quản trị viên {user.email} cho tổ chức {tenant.name}.{warning}"
        })
    except (User.DoesNotExist, Tenant.DoesNotExist):
        return JsonResponse({'error': 'Thông tin cấu hình không hợp lệ.'}, status=404)