from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.contrib.auth import authenticate, login, logout
from apps.tenants.models import Tenant, TenantUser
from django.core.exceptions import ValidationError as DjangoValidationError

class AuthService:
    @staticmethod
    def authenticate_and_login(request, email, password):
        """Xử lý đăng nhập bằng Email"""
        user = authenticate(request, username=email, password=password)
        if user is not None:
            if not user.is_active:
                raise ValidationError("Tài khoản này đã bị vô hiệu hóa.")
            login(request, user)
            return user
        raise ValidationError("Email hoặc mật khẩu không chính xác.")

    @staticmethod
    def logout_user(request):
        """Xử lý đăng xuất"""
        logout(request)

    @staticmethod
    def change_password(user: TenantUser, old_password, new_password):
        """Thay đổi mật khẩu người dùng"""
        if not user.check_password(old_password):
            raise ValidationError("Mật khẩu hiện tại không đúng.")
        if old_password == new_password:
            raise ValidationError("Mật khẩu mới không được trùng với mật khẩu cũ.")

        user.set_password(new_password)
        user.save(update_fields=['password'])
        return user



class TenantService:
    @staticmethod
    def get_list(user):
        """Chỉ Superuser mới xem được danh sách các Tenant"""
        if user.is_superuser:
            return Tenant.objects.all().order_by('-created_at')
        return Tenant.objects.none()

    @staticmethod
    @transaction.atomic  # ✅ Đã có nhưng cần database-level fix
    def create_tenant(name: str, code: str) -> Tenant:
        try:
            return Tenant.objects.create(name=name, code=code)
        except IntegrityError:
            raise ValidationError("Mã định danh (Slug) đã tồn tại trong hệ thống.")

    @staticmethod
    def edit_tenant(user, tenant_id: int, name: str, is_active: bool) -> Tenant:
        if not user.is_superuser:
            raise ValidationError("Bạn không có đặc quyền sửa đổi cấu trúc tổ chức hạ tầng.")
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            tenant.name = name
            tenant.is_active = is_active
            tenant.save(update_fields=['name', 'is_active', 'updated_at'])
            return tenant
        except Tenant.DoesNotExist:
            raise ValidationError("Không tìm thấy tổ chức chỉ định.")


class TenantUserService:
    @staticmethod
    def get_list(user) -> list[TenantUser]:
        queryset = TenantUser.objects.select_related('tenant')

        if user.is_superuser:
            return queryset.all().order_by('-date_joined')
        if not user.tenant:
            return TenantUser.objects.none()
        return queryset.filter(tenant=user.tenant).order_by('-date_joined')

    @staticmethod
    def create_staff(creator, email: str, password_raw: str, full_name: str) -> TenantUser:
        """Khai báo nhân viên mới gán chặt chẽ vào Tenant của Admin tạo nó"""
        if creator.is_superuser:
            raise ValidationError(
                "Hệ thống Superadmin vui lòng khởi tạo tài khoản qua Django Admin hoặc gán Tenant cụ thể trước.")
        if not creator.tenant:
            raise ValidationError("Tài khoản của bạn chưa được gán vào tổ chức nào để có thể tạo nhân viên con.")
        if creator.role != TenantUser.ROLE_TENANT_ADMIN:
            raise ValidationError(
                "Chỉ quản trị viên cấp cao của tổ chức (Tenant Admin) mới có quyền tạo thêm nhân viên.")

        if TenantUser.objects.filter(email=email).exists():
            raise ValidationError("Địa chỉ email này đã được đăng ký trong hệ thống.")
        try:
            validate_password(password_raw)
        except DjangoValidationError as e:
            raise ValidationError(f"Mật khẩu không đủ mạnh: {str(e)}")

        user = TenantUser.objects.create_user(
            email=email,
            password=password_raw,
            full_name=full_name,
            tenant=creator.tenant,
            role=TenantUser.ROLE_TENANT_USER
        )
        return user

    @staticmethod
    def change_status(user, target_user_id: int, is_active: bool) -> TenantUser:
        """Bảo mật: Kiểm tra IDOR - không cho sửa user của tenant khác"""
        try:
            if user.is_superuser:
                target_user = TenantUser.objects.get(id=target_user_id)
            else:
                target_user = TenantUser.objects.get(id=target_user_id, tenant=user.tenant)
                if user.role != TenantUser.ROLE_TENANT_ADMIN:
                    raise ValidationError("Bạn không có quyền thay đổi trạng thái thành viên.")
        except TenantUser.DoesNotExist:
            raise ValidationError("Không tìm thấy tài khoản người dùng hoặc bạn không có quyền quản lý tài khoản này.")

        # Ngăn chặn vô hiệu hóa Tenant Admin hoạt động cuối cùng của Tenant đó
        if not is_active and target_user.role == TenantUser.ROLE_TENANT_ADMIN:
            active_admins = TenantUser.objects.filter(
                tenant=target_user.tenant, role=TenantUser.ROLE_TENANT_ADMIN, is_active=True
            ).exclude(id=target_user.id).count()
            if active_admins == 0:
                raise ValidationError("Không thể vô hiệu hóa: Tổ chức yêu cầu có ít nhất 1 Quản trị viên hoạt động.")

        target_user.is_active = is_active
        target_user.save(update_fields=['is_active'])
        return target_user

    @staticmethod
    def change_role(user, target_user_id: int, new_role: str) -> TenantUser:
        """Bảo mật: Thay đổi chức vụ nhân viên nội bộ"""
        if new_role not in [TenantUser.ROLE_TENANT_ADMIN, TenantUser.ROLE_TENANT_USER]:
            raise ValidationError("Vai trò chuyển đổi không hợp lệ.")

        try:
            if user.is_superuser:
                target_user = TenantUser.objects.get(id=target_user_id)
            else:
                target_user = TenantUser.objects.get(id=target_user_id, tenant=user.tenant)
                if user.role != TenantUser.ROLE_TENANT_ADMIN:
                    raise ValidationError("Chỉ Tenant Admin mới có quyền điều phối cấp bậc nhân viên.")
        except TenantUser.DoesNotExist:
            raise ValidationError("Không tìm thấy thành viên hợp lệ trong cấu trúc tổ chức của bạn.")

        # Ngăn chặn hạ cấp Admin duy nhất
        if target_user.role == TenantUser.ROLE_TENANT_ADMIN and new_role == TenantUser.ROLE_TENANT_USER:
            remaining_admins = TenantUser.objects.filter(
                tenant=target_user.tenant, role=TenantUser.ROLE_TENANT_ADMIN, is_active=True
            ).exclude(id=target_user.id).count()
            if remaining_admins == 0:
                raise ValidationError("Không thể hạ quyền: Tổ chức bắt buộc cần tối thiểu một Tenant Admin.")

        target_user.role = new_role
        target_user.save(update_fields=['role'])
        return target_user

    @staticmethod
    @transaction.atomic
    def assign_tenant_admin(superuser, user_id: int, tenant_id: int) -> tuple[TenantUser, str]:
        """Superadmin điều phối người dùng tự do hoặc từ tổ chức khác vào làm admin của Tenant mới"""
        if not superuser.is_superuser:
            raise ValidationError("Hành động này bị từ chối truy cập nghiêm ngặt.")

        try:
            user = TenantUser.objects.get(id=user_id)
            tenant = Tenant.objects.get(id=tenant_id)
        except (TenantUser.DoesNotExist, Tenant.DoesNotExist):
            raise ValidationError("Thông tin cấu hình tài khoản hoặc tổ chức không tồn tại.")

        warning_msg = ""
        if user.tenant and user.tenant.id != tenant.id:
            warning_msg = f" (Lưu ý hệ thống: Đã bóc tách tài khoản này ra khỏi tổ chức cũ '{user.tenant.name}'.)"

        user.tenant = tenant
        user.role = TenantUser.ROLE_TENANT_ADMIN
        user.is_active = True
        user.save(update_fields=['tenant', 'role', 'is_active'])
        return user, warning_msg

    @staticmethod
    def get_detail(user, user_id: int) -> TenantUser:
        """Xem chi tiết hồ sơ một nhân viên"""
        try:
            if user.is_superuser:
                return TenantUser.objects.get(id=user_id)
            return TenantUser.objects.get(id=user_id, tenant=user.tenant)
        except TenantUser.DoesNotExist:
            raise ValidationError("Không tìm thấy người dùng hoặc bạn không có quyền xem.")

    # Bổ sung vào class TenantUserService trong file services.py

    @staticmethod
    def reset_password(user, target_user_id: int, new_password_raw: str) -> TenantUser:
        """
        Bảo mật: Reset mật khẩu cho nhân viên nội bộ hoặc toàn hệ thống (Superuser)
        """
        try:
            if user.is_superuser:
                target_user = TenantUser.objects.get(id=target_user_id)
            else:
                # Tenant Admin chỉ tìm thấy user thuộc cùng tổ chức (Tenant)
                target_user = TenantUser.objects.get(id=target_user_id, tenant=user.tenant)
                if user.role != TenantUser.ROLE_TENANT_ADMIN:
                    raise ValidationError("Bạn không có quyền reset mật khẩu cho thành viên khác.")
        except TenantUser.DoesNotExist:
            raise ValidationError("Không tìm thấy tài khoản người dùng hoặc bạn không có quyền quản lý tài khoản này.")

        # Validate độ mạnh của mật khẩu mới theo chuẩn Django cấu hình
        try:
            validate_password(new_password_raw, user=target_user)
        except DjangoValidationError as e:
            raise ValidationError(f"Mật khẩu mới không đủ mạnh: {str(e)}")

        # Tiến hành đổi mật khẩu
        target_user.set_password(new_password_raw)
        target_user.save(update_fields=['password'])

        return target_user