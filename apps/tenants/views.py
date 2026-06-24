"""
views.py - Fixed version with proper user creation logic
Phân biệt rõ ràng: Tenant Admin vs Superuser
"""
from datetime import timedelta

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.db import IntegrityError
from django.utils import timezone

from apps.core_networks.services import DomainService, ZimbraServerService
from apps.ssl_manager.models import SSLCertificate
from apps.ssl_manager.services import SSLLifecycleService
from apps.tenants.models import Tenant, TenantUser
from apps.tenants.services import AuthService, TenantUserService, TenantService
from django.contrib.auth import get_user_model, authenticate, login, logout

User = get_user_model()
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# LOGIN & LOGOUT
# ============================================================================

def login_view(request):
    """Trang đăng nhập"""
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
    """Xử lý đăng xuất"""
    AuthService.logout_user(request)
    return redirect('login')


# ============================================================================
# DASHBOARD
# ============================================================================

@login_required(login_url='login')
def dashboard_view(request):
    # 1. Lấy danh sách các đối tượng theo phân quyền người dùng (Tenant / Superuser)
    domains = DomainService.get_list(request.user)
    servers = ZimbraServerService.get_list(request.user)
    certificates = SSLLifecycleService.get_list(request.user)

    # 2. Đếm số lượng tổng quan
    total_domains = domains.count() if hasattr(domains, 'count') else len(domains)
    total_servers = servers.count() if hasattr(servers, 'count') else len(servers)
    total_ssl = certificates.count() if hasattr(certificates, 'count') else len(certificates)

    # 3. Tính toán số lượng chứng chỉ SSL sắp hết hạn (Thời gian hợp lệ còn lại <= 30 ngày)
    # Ngưỡng cảnh báo lấy từ cấu hình Model SSLCertificate.EXPIRY_WARNING_DAYS (30 ngày)
    warning_days = getattr(SSLCertificate, 'EXPIRY_WARNING_DAYS', 30)
    expiry_threshold = timezone.now() + timedelta(days=warning_days)

    # Lọc các chứng chỉ có ngày hết hạn nằm trong khoảng từ hiện tại đến 30 ngày tới
    # Lưu ý: Loại trừ luôn các chứng chỉ trạng thái lỗi nặng hoặc chưa hợp lệ nếu cần thiết
    if hasattr(certificates, 'filter'):
        ssl_expiring_soon = certificates.filter(
            valid_to__gt=timezone.now(),
            valid_to__lte=expiry_threshold
        ).count()
    else:
        ssl_expiring_soon = sum(
            1 for cert in certificates
            if cert.valid_to and timezone.now() < cert.valid_to <= expiry_threshold
        )

    # 4. Đóng gói dữ liệu truyền sang giao diện HTML template
    context = {
        'total_domains': total_domains,
        'total_servers': total_servers,
        'total_ssl': total_ssl,
        'ssl_expiring_soon': ssl_expiring_soon,
    }

    return render(request, 'dashboard.html', context)


# ============================================================================
# ✅ USER LIST VIEW - Truyền tenants list cho superuser
# ============================================================================

@login_required(login_url='login')
def user_list_view(request):
    """
    Hiển thị danh sách nhân viên của tổ chức

    Context:
    - users: Danh sách TenantUser (filtered by role)
    - all_tenants: Danh sách tất cả Tenant (chỉ cho Superuser)
    """
    # ✅ FIX: Lấy danh sách users với select_related để tránh N+1 query
    users = TenantUserService.get_list(request.user)

    # ✅ NEW: Lấy danh sách tenants cho Superuser (dùng trong dropdown)
    all_tenants = []
    if request.user.is_superuser:
        all_tenants = Tenant.objects.all().order_by('-created_at')

    return render(request, 'tenants/user_list.html', {
        'users': users,
        'all_tenants': all_tenants  # ← NEW: Truyền danh sách tenants
    })


# ============================================================================
# ✅ API: CREATE STAFF
# ============================================================================

@login_required(login_url='login')
def api_create_staff(request):
    """
    Tạo nhân viên mới

    LOGIC:
    - Tenant Admin: tự động gán tenant của họ (không cần POST tenant_id)
    - Superuser: PHẢI chỉ định tenant_id trong POST

    POST parameters:
    - email: email của user mới (required)
    - password: mật khẩu text (required)
    - full_name: tên hiển thị (optional)
    - tenant_id: ID tổ chức (required nếu superuser, auto-assign nếu tenant admin)

    Response:
    - Success: {'message': '...', 'user_id': <id>, 'tenant_id': <id>}
    - Error: {'error': '...'}
    """

    # 1️⃣ CHECK METHOD
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # 2️⃣ CHECK PERMISSION - Chỉ Tenant Admin hoặc Superuser
    if not (request.user.is_superuser or request.user.role == TenantUser.ROLE_TENANT_ADMIN):
        logger.warning(f"Unauthorized create_staff attempt by {request.user.email}")
        return JsonResponse({
            'error': 'Bạn không có quyền tạo nhân viên.'
        }, status=403)

    # 3️⃣ GET & VALIDATE INPUT
    email = request.POST.get('email', '').strip()
    password = request.POST.get('password', '').strip()
    full_name = request.POST.get('full_name', '').strip()

    # Validate input không trống
    if not email or not password:
        return JsonResponse({
            'error': 'Email và mật khẩu là bắt buộc.'
        }, status=400)

    # 4️⃣ PHÂN NHÁNH: SUPERUSER vs TENANT ADMIN
    try:
        if request.user.is_superuser:
            # ===== SUPERUSER FLOW =====
            logger.info(f"Superuser {request.user.email} creating staff user")

            # ✅ RULE 1: Bắt buộc chỉ định tenant_id
            tenant_id = request.POST.get('tenant_id', '').strip()
            if not tenant_id:
                return JsonResponse({
                    'error': 'Superuser phải chỉ định tenant_id (Tổ chức mục tiêu).'
                }, status=400)

            # ✅ RULE 2: Validate tenant tồn tại
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                logger.warning(
                    f"Superuser {request.user.email} trying to create user "
                    f"in non-existent tenant {tenant_id}"
                )
                return JsonResponse({
                    'error': 'Tổ chức (Tenant) không tồn tại.'
                }, status=404)

            # ✅ RULE 3: Validate email chưa tồn tại
            if TenantUser.objects.filter(email=email).exists():
                return JsonResponse({
                    'error': 'Email này đã được đăng ký trong hệ thống.'
                }, status=400)

            # ✅ RULE 4: Validate password strength
            try:
                django_validate_password(password)
            except Exception as e:
                return JsonResponse({
                    'error': f'Mật khẩu không đủ mạnh: {str(e)}'
                }, status=400)

            # ✅ RULE 5: Tạo user trực tiếp (không dùng service vì service reject superuser)
            user = TenantUser.objects.create_user(
                email=email,
                password=password,
                full_name=full_name,
                tenant=tenant,
                role=TenantUser.ROLE_TENANT_USER  # Mặc định là staff
            )

            logger.info(
                f"Superuser {request.user.email} created user {email} "
                f"in tenant {tenant.name}"
            )

            return JsonResponse({
                'message': f'✓ Tạo nhân viên {email} cho tổ chức {tenant.name} thành công',
                'user_id': user.id,
                'tenant_id': tenant.id
            })

        else:
            # ===== TENANT ADMIN FLOW =====
            logger.info(
                f"Tenant Admin {request.user.email} creating staff user "
                f"in tenant {request.user.tenant.name}"
            )

            # ✅ Validate Tenant Admin có tenant
            if not request.user.tenant:
                logger.error(f"Tenant Admin {request.user.email} has no tenant assigned!")
                return JsonResponse({
                    'error': 'Tài khoản của bạn chưa được gán vào tổ chức nào.'
                }, status=403)

            # ✅ Gọi service - sẽ tự validate tất cả permission + password strength
            user = TenantUserService.create_staff(
                creator=request.user,  # Pass current user (tenant admin)
                email=email,
                password_raw=password,
                full_name=full_name
            )

            logger.info(
                f"Tenant Admin {request.user.email} created staff {email} "
                f"in tenant {request.user.tenant.name}"
            )

            return JsonResponse({
                'message': f'✓ Tạo nhân viên {email} thành công',
                'user_id': user.id,
                'tenant_id': request.user.tenant.id
            })

    except ValidationError as e:
        # Service layer validation error
        logger.warning(f"Validation error when creating staff: {str(e.message)}")
        return JsonResponse({
            'error': str(e.message)
        }, status=400)
    except IntegrityError as e:
        # Database constraint violation
        logger.error(f"IntegrityError when creating staff: {str(e)}")
        return JsonResponse({
            'error': 'Dữ liệu bị trùng lặp hoặc vi phạm ràng buộc.'
        }, status=400)
    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error creating staff: {str(e)}")
        return JsonResponse({
            'error': 'Lỗi hệ thống không xác định.'
        }, status=500)


# ============================================================================
# API: CHANGE USER STATUS
# ============================================================================

@login_required(login_url='login')
def api_change_user_status(request, user_id):
    """
    Thay đổi trạng thái hoạt động của user (active/inactive)

    BẢO MẬT: IDOR check
    - Tenant Admin: chỉ sửa được user trong tenant của họ
    - Superuser: sửa được user của bất kỳ tenant nào

    POST parameters:
    - is_active: 'true' hoặc 'false'
    """

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # ✅ FIX: Use constant thay vì string literal
    if not (request.user.is_superuser or request.user.role == TenantUser.ROLE_TENANT_ADMIN):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    is_active = request.POST.get('is_active') == 'true'

    try:
        target_user = User.objects.get(id=user_id)

        # ✅ IDOR Check: Tenant Admin chỉ sửa được user trong tenant của họ
        if not request.user.is_superuser and target_user.tenant != request.user.tenant:
            logger.warning(
                f"IDOR attempt: {request.user.email} trying to change status "
                f"of {target_user.email} in different tenant"
            )
            return JsonResponse({
                'error': 'Bạn không có quyền chỉnh sửa thành viên của tổ chức khác.'
            }, status=403)

        # ✅ FIX: Gọi đúng tên hàm - change_status (không phải change_user_status)
        TenantUserService.change_status(request.user, user_id, is_active)

        return JsonResponse({'message': 'Cập nhật trạng thái thành công'})

    except User.DoesNotExist:
        return JsonResponse({
            'error': 'Không tìm thấy tài khoản người dùng cần cập nhật.'
        }, status=404)
    except ValidationError as e:
        logger.warning(f"Validation error changing status: {str(e.message)}")
        return JsonResponse({
            'error': str(e.message)
        }, status=400)


# ============================================================================
# API: CHANGE USER ROLE
# ============================================================================

@login_required(login_url='login')
def api_change_user_role(request, user_id):
    """
    Thay đổi vai trò của user (tenant_admin hoặc tenant_user)

    Chỉ Tenant Admin hoặc Superuser mới được thay đổi

    POST parameters:
    - role: 'tenant_admin' hoặc 'tenant_user'
    """

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    new_role = request.POST.get('role', '').strip()

    try:
        # ✅ Gọi service để validate tất cả permission + business logic
        target_user = TenantUserService.change_role(request.user, user_id, new_role)

        return JsonResponse({
            'message': f'Đã cập nhật vai trò của {target_user.email} thành {target_user.get_role_display()}.',
            'role': target_user.role,
        })
    except ValidationError as e:
        logger.warning(f"Validation error changing role: {str(e.message)}")
        return JsonResponse({
            'error': str(e.message)
        }, status=400)


# ============================================================================
# TENANT MANAGEMENT (Superuser only)
# ============================================================================

@login_required(login_url='login')
def tenant_list(request):
    """Hiển thị trang quản trị danh sách tổ chức (Chỉ dành cho Superadmin)"""
    if not request.user.is_superuser:
        return render(request, 'errors/403.html', {
            'error': 'Chỉ có nhà phát triển hệ thống mới được vào phân hệ này.'
        })

    tenants = Tenant.objects.all().order_by('-created_at')
    unassigned_users = User.objects.filter(is_superuser=False).select_related('tenant')

    return render(request, 'tenants/tenant_list.html', {
        'tenants': tenants,
        'unassigned_users': unassigned_users
    })


@login_required(login_url='login')
def api_add_tenant(request):
    """Tạo tenant mới (Superuser only)"""
    if request.method != 'POST' or not request.user.is_superuser:
        return JsonResponse({'error': 'Từ chối truy cập'}, status=403)

    name = request.POST.get('name', '').strip()
    code = request.POST.get('code', '').strip().upper()

    if not name or not code:
        return JsonResponse({
            'error': 'Tên và mã định danh tổ chức là bắt buộc.'
        }, status=400)

    try:
        tenant = TenantService.create_tenant(name, code)
        return JsonResponse({
            'message': f"Đã khởi tạo thành công không gian làm việc cho {tenant.name}."
        })
    except ValidationError as e:
        return JsonResponse({
            'error': str(e.message)
        }, status=400)


@login_required(login_url='login')
def api_edit_tenant(request, tenant_id):
    """Sửa thông tin tenant (Superuser only)"""
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
    """Xóa tenant (Superuser only)"""
    if request.method != 'POST' or not request.user.is_superuser:
        return JsonResponse({'error': 'Từ chối truy cập'}, status=403)

    try:
        tenant = Tenant.objects.get(id=tenant_id)
        if tenant.users.exists():
            return JsonResponse({
                'error': 'Không thể xóa! Tổ chức này còn có nhân viên hoặc hạ tầng ràng buộc.'
            }, status=400)
        tenant.delete()
        return JsonResponse({'message': 'Đã xóa dữ liệu Tenant khỏi hệ thống.'})
    except Tenant.DoesNotExist:
        return JsonResponse({'error': 'Không tìm thấy dữ liệu.'}, status=404)


@login_required(login_url='login')
def api_assign_tenant_admin(request):
    """
    Đặc quyền: Gán user vào Tenant và nâng cấp thành tenant_admin
    (Superuser only)
    """
    if request.method != 'POST' or not request.user.is_superuser:
        return JsonResponse({'error': 'Từ chối truy cập'}, status=403)

    user_id = request.POST.get('user_id', '').strip()
    tenant_id = request.POST.get('tenant_id', '').strip()

    try:
        user, warning = TenantUserService.assign_tenant_admin(
            superuser=request.user,
            user_id=int(user_id),
            tenant_id=int(tenant_id)
        )

        return JsonResponse({
            'message': f"Đã chỉ định quyền quản trị viên {user.email} "
                       f"cho tổ chức {user.tenant.name}.{warning}"
        })
    except ValueError:
        return JsonResponse({
            'error': 'ID không hợp lệ.'
        }, status=400)
    except ValidationError as e:
        return JsonResponse({
            'error': str(e.message)
        }, status=400)
    except (User.DoesNotExist, Tenant.DoesNotExist):
        return JsonResponse({
            'error': 'Thông tin cấu hình không hợp lệ.'
        }, status=404)