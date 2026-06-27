"""
apps/mailbox/services.py - UPDATED

Service layer cho chức năng "Tìm kiếm & Quản lý Email" (Mailbox).
Toàn bộ thao tác đọc/sửa account đều gọi trực tiếp lên Zimbra qua SOAP Admin
API (ZimbraAdminSoapClient), KHÔNG lưu thông tin mailbox vào DB cục bộ --
DB cục bộ chỉ giữ Domain/Server/Tenant để biết phải gọi server nào.

⭐ UPDATED:
- Thêm hàm create_account()
- Bổ sung zimbraMailQuota (quota, MB) + zimbraMailSize (used, MB) vào detail
"""
from django.core.exceptions import ValidationError
import re

from apps.core_networks.models import Domain
from apps.core_networks.zimbra_soap import ZimbraAdminSoapClient


# Các field hồ sơ cho phép xem/sửa qua màn hình tìm kiếm email.
PROFILE_ATTRS = ["givenName", "sn", "displayName", "title", "mobile"]


def bytes_to_mb(bytes_val):
    """Convert bytes to MB, handle None/0 gracefully"""
    if not bytes_val or bytes_val == 0:
        return 0
    try:
        return int(bytes_val) / (1024 * 1024)
    except (TypeError, ValueError):
        return 0


class MailboxPermissionService:
    """Tách riêng phần kiểm tra quyền để tái dùng ở mọi action (search/edit/...)."""

    @staticmethod
    def get_allowed_domains(user):
        """Danh sách Domain mà user hiện tại được phép tìm kiếm/quản lý email."""
        if user.is_superuser:
            return Domain.objects.select_related('server', 'tenant').filter(is_active=True).order_by('name')
        if not user.tenant:
            return Domain.objects.none()
        return Domain.objects.select_related('server', 'tenant').filter(
            tenant=user.tenant, is_active=True
        ).order_by('name')

    @staticmethod
    def get_domain_or_403(user, domain_id: int) -> Domain:
        """Lấy 1 Domain cụ thể, raise nếu user không có quyền truy cập domain đó."""
        try:
            domain = Domain.objects.select_related('server', 'tenant').get(id=domain_id)
        except Domain.DoesNotExist:
            raise ValidationError("Không tìm thấy tên miền chỉ định.")

        if user.is_superuser:
            return domain
        if not user.tenant or domain.tenant_id != user.tenant_id:
            raise ValidationError("Bạn không có quyền truy cập tên miền này.")
        return domain

    @staticmethod
    def can_manage_account(user) -> bool:
        """
        Superuser và Tenant Admin được tạo/sửa/xóa/khóa/đổi tên/backup.
        Nhân viên (tenant_user) chỉ được Reset Password (kiểm tra riêng ở action đó).
        """
        from apps.tenants.models import TenantUser
        return user.is_superuser or user.role == TenantUser.ROLE_TENANT_ADMIN


class MailboxService:

    @staticmethod
    def _get_client_for_domain(domain: Domain) -> ZimbraAdminSoapClient:
        if not domain.server:
            raise ValidationError("Tên miền này chưa được gán Máy chủ Zimbra để thao tác.")
        return ZimbraAdminSoapClient(domain.server)

    @staticmethod
    def _ensure_email_in_domain(email: str, domain: Domain):
        """Chặn truy cập account thuộc domain khác qua việc giả mạo email -- IDOR."""
        suffix = f"@{domain.name}".lower()
        if not email.lower().strip().endswith(suffix):
            raise ValidationError("Địa chỉ email không thuộc tên miền đã chọn.")

    # Số lượng record trả về cho mỗi lần load (infinite scroll phía client).
    SEARCH_PAGE_SIZE = 25

    @staticmethod
    def search(user, domain_id: int, query: str, offset: int = 0) -> dict:
        """
        Tìm kiếm account theo email (chứa chuỗi `query`) trong 1 domain được phép.
        Trả về dict {results, has_more} để client biết còn dữ liệu để tải tiếp.
        """
        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        if not query or not query.strip():
            raise ValidationError("Vui lòng nhập từ khóa email cần tìm kiếm.")

        if offset < 0:
            offset = 0

        page_size = MailboxService.SEARCH_PAGE_SIZE
        client = MailboxService._get_client_for_domain(domain)
        raw_results = client.search_account(
            query.strip(), domain.name, limit=page_size + 1, offset=offset
        )

        has_more = len(raw_results) > page_size
        raw_results = raw_results[:page_size]

        results = []
        for attrs in raw_results:
            quota_mb = bytes_to_mb(attrs.get("zimbraMailQuota"))
            used_mb = bytes_to_mb(attrs.get("zimbraMailSize"))

            results.append({
                "email": attrs.get("name") or attrs.get("mail", ""),
                "givenName": attrs.get("givenName", ""),
                "sn": attrs.get("sn", ""),
                "displayName": attrs.get("displayName", ""),
                "title": attrs.get("title", ""),
                "mobile": attrs.get("mobile", ""),
                "status": attrs.get("zimbraAccountStatus", "active"),
                "quota_mb": round(quota_mb, 2),
                "used_mb": round(used_mb, 2),
            })
        return {"results": results, "has_more": has_more}

    @staticmethod
    def get_detail(user, domain_id: int, email: str) -> dict:
        """⭐ UPDATED: Thêm quota_mb + used_mb"""
        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        MailboxService._ensure_email_in_domain(email, domain)

        client = MailboxService._get_client_for_domain(domain)
        attrs = client.get_account(email)

        quota_mb = bytes_to_mb(attrs.get("zimbraMailQuota"))
        used_mb = bytes_to_mb(attrs.get("zimbraMailSize"))

        return {
            "email": attrs.get("name", email),
            "givenName": attrs.get("givenName", ""),
            "sn": attrs.get("sn", ""),
            "displayName": attrs.get("displayName", ""),
            "title": attrs.get("title", ""),
            "mobile": attrs.get("mobile", ""),
            "status": attrs.get("zimbraAccountStatus", "active"),
            "quota_mb": round(quota_mb, 2),
            "used_mb": round(used_mb, 2),
        }

    @staticmethod
    def create_account(user, domain_id: int, email: str, password: str,
                      given_name: str = "", sn: str = "", display_name: str = "",
                      quota_mb: int = 1024) -> dict:
        """
        ⭐ NEW: Tạo tài khoản email mới

        Quyền: Chỉ Superuser/Tenant Admin
        Validation:
        - Email phải hợp lệ (format)
        - Password phải mạnh (8 ký tự, hoa, thường, số, đặc biệt)
        - Quota: 0 = không giới hạn, hoặc >= 100 MB (tối đa 10240 MB)
        """
        if not MailboxPermissionService.can_manage_account(user):
            raise ValidationError("Bạn không có quyền tạo tài khoản email.")

        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)

        # Validate email format
        email = email.strip().lower()
        if not re.match(r'^[a-z0-9][a-z0-9._%-]*[a-z0-9]@', email):
            raise ValidationError("Định dạng email không hợp lệ.")

        MailboxService._ensure_email_in_domain(email, domain)

        # Validate password strength
        if not password or len(password) < 8:
            raise ValidationError("Mật khẩu phải có ít nhất 8 ký tự.")

        if not re.search(r'[A-Z]', password):
            raise ValidationError("Mật khẩu phải có ít nhất 1 chữ hoa (A-Z).")

        if not re.search(r'[a-z]', password):
            raise ValidationError("Mật khẩu phải có ít nhất 1 chữ thường (a-z).")

        if not re.search(r'\d', password):
            raise ValidationError("Mật khẩu phải có ít nhất 1 số (0-9).")

        if not re.search(r'[!@#$%^&*\-_=+\[\]{}\(\)|;:\'\"<>,.?/~`]', password):
            raise ValidationError("Mật khẩu phải có ít nhất 1 ký tự đặc biệt (!@#$%^&*-_=+...).")

        # Validate quota. 0 = không giới hạn (zimbraMailQuota=0 trên Zimbra
        # nghĩa là bỏ giới hạn dung lượng), nên không áp ràng buộc tối thiểu
        # 100MB cho trường hợp này.
        try:
            quota_mb = int(quota_mb)
        except (TypeError, ValueError):
            quota_mb = 1024

        if quota_mb < 0:
            raise ValidationError("Quota không được nhỏ hơn 0.")

        if 0 < quota_mb < 100:
            raise ValidationError("Quota tối thiểu là 100 MB (hoặc nhập 0 để không giới hạn).")

        if quota_mb > 10240:
            raise ValidationError("Quota tối đa là 10 GB (10240 MB).")

        # Prepare profile
        profile = {
            "givenName": given_name.strip(),
            "sn": sn.strip(),
            "displayName": display_name.strip() or (given_name.strip() + " " + sn.strip()).strip(),
            "zimbraMailQuota": str(quota_mb * 1024 * 1024),  # 0 -> "0" (không giới hạn)
        }

        # Call Zimbra API
        client = MailboxService._get_client_for_domain(domain)
        client.create_account(email, password, profile)

        return {
            "email": email,
            "givenName": given_name,
            "sn": sn,
            "displayName": profile["displayName"],
            "quota_mb": quota_mb,
            "used_mb": 0,
        }

    @staticmethod
    def update_profile(user, domain_id: int, email: str, profile: dict, quota_mb=None) -> None:
        """
        Sửa thông tin givenName/sn/displayName/title/mobile, và (tùy chọn)
        zimbraMailQuota. Superuser & Tenant Admin.

        `quota_mb`: None -> không đổi quota hiện tại; 0 -> không giới hạn;
        >0 -> đặt quota theo MB (>=100, <=10240).
        """
        if not MailboxPermissionService.can_manage_account(user):
            raise ValidationError("Bạn không có quyền chỉnh sửa thông tin tài khoản email.")

        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        MailboxService._ensure_email_in_domain(email, domain)

        # Chỉ truyền các field hợp lệ trong PROFILE_ATTRS
        safe_profile = {k: v for k, v in profile.items() if k in PROFILE_ATTRS}

        if quota_mb is not None and quota_mb != "":
            try:
                quota_mb = int(quota_mb)
            except (TypeError, ValueError):
                raise ValidationError("Quota không hợp lệ.")

            if quota_mb < 0:
                raise ValidationError("Quota không được nhỏ hơn 0.")
            if 0 < quota_mb < 100:
                raise ValidationError("Quota tối thiểu là 100 MB (hoặc nhập 0 để không giới hạn).")
            if quota_mb > 10240:
                raise ValidationError("Quota tối đa là 10 GB (10240 MB).")

            # 0 -> "0" (không giới hạn). modify_account() chỉ bỏ qua giá trị
            # rỗng/None, "0" vẫn được gửi đi như một giá trị hợp lệ.
            safe_profile["zimbraMailQuota"] = str(quota_mb * 1024 * 1024)

        client = MailboxService._get_client_for_domain(domain)
        client.modify_account(email, safe_profile)

    @staticmethod
    def reset_password(user, domain_id: int, email: str, new_password: str) -> None:
        """
        Reset password -- DUY NHẤT hành động mà Nhân viên (tenant_user) cũng được
        phép thực hiện.
        """
        password_regex = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&._-])"

        if not re.match(password_regex, new_password):
            raise ValidationError(
                "Mật khẩu phải bao gồm cả chữ hoa, chữ thường, chữ số và ký tự đặc biệt (ví dụ: @, $, !, %, *, ?, &, ., _, -)."
            )

        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        MailboxService._ensure_email_in_domain(email, domain)

        client = MailboxService._get_client_for_domain(domain)
        client.set_password(email, new_password)

    @staticmethod
    def rename(user, domain_id: int, email: str, new_email: str) -> None:
        if not MailboxPermissionService.can_manage_account(user):
            raise ValidationError("Bạn không có quyền đổi tên địa chỉ email.")

        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        MailboxService._ensure_email_in_domain(email, domain)
        MailboxService._ensure_email_in_domain(new_email, domain)

        client = MailboxService._get_client_for_domain(domain)
        client.rename_account(email, new_email)

    @staticmethod
    def set_status(user, domain_id: int, email: str, status: str) -> None:
        """status: active | locked | closed"""
        if not MailboxPermissionService.can_manage_account(user):
            raise ValidationError("Bạn không có quyền thay đổi trạng thái tài khoản email.")

        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        MailboxService._ensure_email_in_domain(email, domain)

        client = MailboxService._get_client_for_domain(domain)
        client.set_account_status(email, status)

    @staticmethod
    def delete(user, domain_id: int, email: str) -> None:
        """Xóa vĩnh viễn account -- chỉ Superuser/Tenant Admin."""
        if not MailboxPermissionService.can_manage_account(user):
            raise ValidationError("Bạn không có quyền xóa tài khoản email.")

        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        MailboxService._ensure_email_in_domain(email, domain)

        client = MailboxService._get_client_for_domain(domain)
        client.delete_account(email)

    @staticmethod
    def get_backup_target(user, domain_id: int, email: str):
        """Lấy server + email để stream backup .tgz về client"""
        if not MailboxPermissionService.can_manage_account(user):
            raise ValidationError("Bạn không có quyền tải dữ liệu sao lưu hộp thư.")

        domain = MailboxPermissionService.get_domain_or_403(user, domain_id)
        MailboxService._ensure_email_in_domain(email, domain)

        if not domain.server:
            raise ValidationError("Tên miền này chưa được gán Máy chủ Zimbra để sao lưu.")
        return domain.server, email