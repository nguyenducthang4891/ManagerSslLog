from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth import authenticate, login, logout
from apps.tenants.models import Tenant, TenantUser


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
    def create_tenant_with_admin(name: str, code: str, admin_email: str, admin_password: str) -> Tenant:
        """Tạo mới Tenant và tài khoản Admin đi kèm trong một Transaction"""
        code = code.lower().strip()
        if Tenant.objects.filter(code=code).exists():
            raise ValidationError("Mã định danh (Subdomain) này đã được sử dụng.")
        if TenantUser.objects.filter(email=admin_email).exists():
            raise ValidationError("Email này đã được đăng ký trên hệ thống.")

        with transaction.atomic():
            tenant = Tenant.objects.create(name=name, code=code)
            TenantUser.objects.create_user(
                email=admin_email,
                password=admin_password,
                tenant=tenant,
                role=TenantUser.ROLE_TENANT_ADMIN,
                is_staff=False
            )
            return tenant

    @staticmethod
    def update_tenant(tenant_id: int, name: str = None, is_active: bool = None) -> Tenant:
        """Cập nhật thông tin cấu hình Tenant"""
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Không tìm thấy Tenant cần cập nhật.")

        update_fields = []
        if name is not None:
            tenant.name = name
            update_fields.append('name')
        if is_active is not None:
            tenant.is_active = is_active
            update_fields.append('is_active')

        if update_fields:
            tenant.save(update_fields=update_fields)
        return tenant

    @staticmethod
    def delete_tenant(tenant_id: int):
        """
        Xóa tổ chức (Cascade xóa sạch user liên quan vì TenantUser.tenant dùng on_delete=CASCADE).
        Domain dùng on_delete=SET_NULL với Tenant, nên domain KHÔNG bị xóa cascade --
        chúng chỉ mất liên kết tenant (trở thành "tự do"). Việc chặn xóa khi còn domain
        được thực hiện ở views.py (api_delete_tenant).
        """
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Không tìm thấy Tenant cần xóa.")
        tenant.delete()

    @staticmethod
    def get_list(user) -> list[Tenant]:
        """Lấy danh sách các Tenant (Chỉ Superadmin hệ thống mới có quyền)"""
        if not user.is_superuser:
            raise ValidationError("Bạn không có quyền truy cập danh sách tổ chức hệ thống.")
        return Tenant.objects.all().order_by('-created_at')

    @staticmethod
    def get_detail(user, tenant_id: int) -> Tenant:
        """Xem chi tiết thông tin một Tenant"""
        if not user.is_superuser and (not user.tenant or user.tenant.id != tenant_id):
            raise ValidationError("Bạn không có quyền truy cập thông tin tổ chức này.")
        try:
            return Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise ValidationError("Không tìm thấy tổ chức chỉ định.")


class TenantUserService:
    @staticmethod
    def create_staff(tenant: Tenant, email: str, password: str, full_name: str = "") -> TenantUser:
        """Admin tạo thêm nhân viên (Staff) cấp dưới thuộc cùng Tenant"""
        if TenantUser.objects.filter(email=email).exists():
            raise ValidationError("Email nhân viên đã tồn tại trên hệ thống.")

        return TenantUser.objects.create_user(
            email=email,
            password=password,
            tenant=tenant,
            full_name=full_name,
            role=TenantUser.ROLE_TENANT_USER
        )

    @staticmethod
    def change_user_status(tenant: Tenant, user_id: int, is_active: bool):
        """Bật/Tắt trạng thái hoạt động của nhân viên nội bộ"""
        try:
            user = TenantUser.objects.get(id=user_id, tenant=tenant)
        except TenantUser.DoesNotExist:
            raise ValidationError("Không tìm thấy người dùng thuộc tổ chức của bạn.")

        if user.role == TenantUser.ROLE_TENANT_ADMIN:
            raise ValidationError("Không thể vô hiệu hóa tài khoản Admin chính.")

        user.is_active = is_active
        user.save(update_fields=['is_active'])
        return user

    @staticmethod
    def change_user_role(acting_user: TenantUser, target_user_id: int, new_role: str) -> TenantUser:
        """
        MỚI: Cho phép Tenant Admin tự nâng/hạ quyền (tenant_admin <-> tenant_user)
        cho nhân viên TRONG CHÍNH tổ chức của mình, không cần Superuser duyệt.

        Ràng buộc an toàn:
        - acting_user phải là superuser HOẶC tenant_admin của CHÍNH tenant chứa target_user.
        - Không tự hạ quyền chính bản thân mình (tránh tự khóa quyền truy cập,
          vd. admin duy nhất tự hạ quyền xuống staff sẽ không ai quản lý tổ chức nữa).
        - Nếu hạ quyền tenant_admin -> tenant_user, tổ chức phải còn LẠI ÍT NHẤT
          1 tenant_admin khác đang hoạt động sau khi hạ quyền (không để tổ chức
          rơi vào trạng thái không có ai quản lý).
        - new_role phải là 1 trong các giá trị hợp lệ của TenantUser.ROLE_CHOICES.
        """
        valid_roles = dict(TenantUser.ROLE_CHOICES)
        if new_role not in valid_roles:
            raise ValidationError("Vai trò chỉ định không hợp lệ.")

        try:
            target_user = TenantUser.objects.get(id=target_user_id)
        except TenantUser.DoesNotExist:
            raise ValidationError("Không tìm thấy người dùng cần đổi quyền.")

        # Quyền hạn: Superuser thao tác tự do; Tenant Admin chỉ thao tác trong tenant của mình.
        if not acting_user.is_superuser:
            if acting_user.role != TenantUser.ROLE_TENANT_ADMIN:
                raise ValidationError("Chỉ Tenant Admin hoặc Superuser mới có quyền thay đổi vai trò nhân viên.")
            if not acting_user.tenant or target_user.tenant_id != acting_user.tenant_id:
                raise ValidationError("Bạn chỉ có thể thay đổi vai trò nhân viên thuộc tổ chức của mình.")

        if target_user.id == acting_user.id and new_role != acting_user.role:
            raise ValidationError("Bạn không thể tự thay đổi vai trò của chính tài khoản mình.")

        if target_user.role == new_role:
            return target_user  # không có gì để đổi

        # Nếu đang hạ quyền một Tenant Admin xuống Staff, đảm bảo tổ chức còn admin khác.
        if target_user.role == TenantUser.ROLE_TENANT_ADMIN and new_role == TenantUser.ROLE_TENANT_USER:
            remaining_admins = TenantUser.objects.filter(
                tenant=target_user.tenant,
                role=TenantUser.ROLE_TENANT_ADMIN,
                is_active=True,
            ).exclude(id=target_user.id).count()

            if remaining_admins == 0:
                raise ValidationError(
                    "Không thể hạ quyền: tổ chức cần có ít nhất một Tenant Admin đang hoạt động."
                )

        target_user.role = new_role
        target_user.save(update_fields=['role'])
        return target_user

    @staticmethod
    def get_list(user) -> list[TenantUser]:
        """Lấy danh sách nhân viên thuộc tổ chức của User đang đăng nhập"""
        if user.is_superuser:
            return TenantUser.objects.all().order_by('-date_joined')
        if not user.tenant:
            return TenantUser.objects.none()
        return TenantUser.objects.filter(tenant=user.tenant).order_by('-date_joined')

    @staticmethod
    def get_detail(user, user_id: int) -> TenantUser:
        """Xem chi tiết hồ sơ một nhân viên"""
        try:
            if user.is_superuser:
                return TenantUser.objects.get(id=user_id)
            return TenantUser.objects.get(id=user_id, tenant=user.tenant)
        except TenantUser.DoesNotExist:
            raise ValidationError("Không tìm thấy người dùng hoặc bạn không có quyền xem.")