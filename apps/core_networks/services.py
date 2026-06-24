from io import StringIO
import paramiko
from django.core.exceptions import ValidationError
from django.db import models
from apps.core_networks.models import ZimbraServer, Domain
from apps.core_networks.zimbra_soap import ZimbraAdminSoapClient
from apps.tenants.models import Tenant
from apps.utils.validate import DOMAIN_REGEX


def _load_private_key(key_text: str):
    """
    FIX: paramiko.RSAKey.from_private_key chỉ hỗ trợ RSA. Nhiều người dùng dùng
    ED25519/ECDSA/DSA key. Thử lần lượt các loại key phổ biến trước khi báo lỗi.
    """
    key_classes = [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]
    last_error = None
    for key_cls in key_classes:
        try:
            return key_cls.from_private_key(StringIO(key_text))
        except paramiko.SSHException as e:
            last_error = e
            continue
    raise paramiko.SSHException(f"Không thể nhận diện loại Private Key (đã thử RSA/Ed25519/ECDSA/DSS): {last_error}")


class ZimbraServerService:
    @staticmethod
    def add_server(name: str, hostname: str, port: int, username: str,
                   zimbra_admin_email: str, zimbra_admin_password: str,
                   password: str = "", key: str = "") -> ZimbraServer:
        """Thêm mới một cụm Mail Server Zimbra vào hệ thống với đầy đủ thông tin SSH và SOAP Admin"""
        if not password and not key:
            raise ValidationError("Bắt buộc phải cung cấp SSH Password hoặc Private Key để kết nối SSH.")

        if not zimbra_admin_email or not zimbra_admin_password:
            raise ValidationError("Bắt buộc phải cung cấp Tài khoản và Mật khẩu ứng dụng Admin của Zimbra.")

        return ZimbraServer.objects.create(
            name=name,
            hostname=hostname.strip(),
            port=port,
            username=username,
            ssh_password=password,
            ssh_key=key,
            zimbra_admin_email=zimbra_admin_email.strip(),
            zimbra_admin_password=zimbra_admin_password
        )

    @staticmethod
    def update_server(server_id: int, **fields) -> ZimbraServer:
        """Cập nhật thông số cấu hình SSH, SOAP hoặc thông tin máy chủ"""
        try:
            server = ZimbraServer.objects.get(id=server_id)
        except ZimbraServer.DoesNotExist:
            raise ValidationError("Không tìm thấy Zimbra Server chỉ định.")

        # FIX: zimbra_admin_email là trường bắt buộc để login SOAP, không cho phép
        # ghi đè thành rỗng/None một cách vô tình -- chỉ update khi có giá trị thật.
        allowed_fields = [
            'name', 'hostname', 'port', 'username', 'ssh_password', 'ssh_key',
            'zimbra_home', 'zimbra_admin_email', 'zimbra_admin_password'
        ]
        update_fields = []

        for key, value in fields.items():
            if key not in allowed_fields:
                continue
            if value is None or value == "":
                continue
            setattr(server, key, value)
            update_fields.append(key)

        if update_fields:
            server.save(update_fields=update_fields)
        return server

    @staticmethod
    def delete_server(server_id: int):
        """Xóa hạ tầng server (Bị chặn bởi models.PROTECT nếu có domain đang gán vào)"""
        try:
            server = ZimbraServer.objects.get(id=server_id)
        except ZimbraServer.DoesNotExist:
            raise ValidationError("Không tìm thấy server cần xóa.")
        server.delete()

    @staticmethod
    def get_list(user) -> list[ZimbraServer]:
        """Lấy danh sách Mail Server có phân quyền cô lập dữ liệu"""
        if user.is_superuser:
            return ZimbraServer.objects.all().order_by('-created_at')
        if not user.tenant:
            return ZimbraServer.objects.none()

        return ZimbraServer.objects.filter(
            models.Q(tenant__isnull=True) | models.Q(tenant=user.tenant)
        ).order_by('-created_at')

    @staticmethod
    def get_detail(user, server_id: int) -> ZimbraServer:
        """Xem chi tiết cấu hình máy chủ"""
        try:
            if user.is_superuser:
                return ZimbraServer.objects.get(id=server_id)
            return ZimbraServer.objects.get(
                models.Q(id=server_id) &
                (models.Q(tenant__isnull=True) | models.Q(tenant=user.tenant))
            )
        except ZimbraServer.DoesNotExist:
            raise ValidationError("Máy chủ không tồn tại hoặc bạn không có quyền xem.")

    @staticmethod
    def test_ssh_connection(server_id: int) -> tuple[bool, str]:
        """
        Kiểm tra kết nối SSH tới server dựa trên server_id.
        Trả về: (Trạng thái thành công: True/False, Tin nhắn thông báo)
        """
        try:
            server = ZimbraServer.objects.get(id=server_id)
        except ZimbraServer.DoesNotExist:
            return False, "Không tìm thấy thông tin máy chủ hạ tầng."

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            if server.ssh_key:
                pkey = _load_private_key(server.ssh_key)
                ssh.connect(server.hostname, port=server.port, username=server.username, pkey=pkey, timeout=5)
            else:
                ssh.connect(server.hostname, port=server.port, username=server.username, password=server.ssh_password,
                            timeout=5)

            return True, "Kết nối SSH tới máy chủ thành công!"
        except paramiko.AuthenticationException:
            return False, "Sai tài khoản, mật khẩu hoặc Private Key SSH."
        except paramiko.SSHException as ssh_err:
            return False, f"Lỗi giao thức SSH: {str(ssh_err)}"
        except Exception as e:
            return False, f"Không thể kết nối (Timeout/Sai IP Port): {str(e)}"
        finally:
            ssh.close()


class DomainService:

    @staticmethod
    def _check_tenant_can_use_server(tenant: Tenant | None, server: ZimbraServer, is_superuser: bool):
        """
        Quy tắc dùng chung: server không gán tenant (shared) -> ai cũng dùng được.
        Server có gán tenant (dedicated) -> chỉ tenant đó hoặc superuser được dùng.
        """
        if server.tenant and server.tenant != tenant and not is_superuser:
            raise ValidationError("Bạn không có quyền gán tên miền vào Server chuyên dụng của tổ chức khác.")

    @staticmethod
    def add_domain(tenant: Tenant, domain_name: str, server_id: int, is_superuser: bool = False,
                   create_on_zimbra: bool = True) -> Domain:
        if not domain_name:
            raise ValidationError("Tên miền không được để trống.")

        domain_name = domain_name.lower().strip()

        # VALIDATE ĐỊNH DẠNG DOMAIN
        if not DOMAIN_REGEX.match(domain_name):
            raise ValidationError(
                f"Định dạng tên miền '{domain_name}' không hợp lệ (Ví dụ đúng: company.com, mail.site.vn).")

        if Domain.objects.filter(name=domain_name).exists():
            raise ValidationError(f"Tên miền {domain_name} đã tồn tại trên hệ thống quản lý cục bộ.")

        try:
            server = ZimbraServer.objects.get(id=server_id)
        except ZimbraServer.DoesNotExist:
            raise ValidationError("Hạ tầng Server chỉ định không tồn tại hoặc không hợp lệ.")

        DomainService._check_tenant_can_use_server(tenant, server, is_superuser)

        # Thực tế tạo trên hạ tầng
        if create_on_zimbra:
            client = ZimbraAdminSoapClient(server)
            if client.domain_exists(domain_name):
                raise ValidationError(f"Tên miền '{domain_name}' đã cấu hình sẵn trên Mail Server vật lý.")
            client.create_domain(domain_name)

        # Lưu lại trạng thái đồng bộ vật lý vào DB thông qua thuộc tính is_created_on_zimbra
        return Domain.objects.create(
            tenant=tenant,
            name=domain_name,
            server=server,
            is_created_on_zimbra=create_on_zimbra
        )

    @staticmethod
    def change_domain_server(user, domain_id: int, new_server_id: int) -> Domain:
        """
        FIX (bug #10 trong review): đổi server quản lý domain phải đồng bộ THẬT với Zimbra,
        không chỉ đổi con trỏ DB. Nếu domain chưa tồn tại trên server mới, tạo nó trên đó.
        Domain cũ trên server cũ sẽ không bị xóa tự động (cần xử lý thủ công / job riêng
        để tránh mất mailbox ngoài ý muốn khi rollback).
        """
        try:
            if user.is_superuser:
                domain = Domain.objects.get(id=domain_id)
            else:
                domain = Domain.objects.get(id=domain_id, tenant=user.tenant)
        except Domain.DoesNotExist:
            raise ValidationError("Không tìm thấy tên miền hoặc bạn không có quyền thực hiện hành động này.")

        try:
            new_server = ZimbraServer.objects.get(id=new_server_id)
        except ZimbraServer.DoesNotExist:
            raise ValidationError("Hạ tầng Server chỉ định không tồn tại hoặc không hợp lệ.")

        DomainService._check_tenant_can_use_server(user.tenant, new_server, user.is_superuser)

        if new_server.id == domain.server_id:
            return domain  # không có gì để đổi

        client = ZimbraAdminSoapClient(new_server)
        if not client.domain_exists(domain.name):
            client.create_domain(domain.name)

        domain.server = new_server
        domain.save(update_fields=['server'])
        return domain

    @staticmethod
    def change_domain_status(user, domain_id: int, is_active: bool) -> Domain:
        """
        Bật/Tắt trạng thái hoạt động (Khai thác) của Domain.
        FIX: hỗ trợ nhánh superuser, trước đây luôn filter tenant=user.tenant
        khiến superuser (tenant=None) không tắt/mở được domain đã gán cho tenant khác.
        """
        try:
            if user.is_superuser:
                domain = Domain.objects.get(id=domain_id)
            else:
                domain = Domain.objects.get(id=domain_id, tenant=user.tenant)
        except Domain.DoesNotExist:
            raise ValidationError("Không tìm thấy tên miền này trong phạm vi tổ chức của bạn.")

        domain.is_active = is_active
        domain.save(update_fields=['is_active'])
        return domain

    @staticmethod
    def delete_domain(user, domain_id: int):
        """
        Xóa Domain khỏi hệ thống (Cascade tự động dọn sạch cấu hình SSL liên quan).
        FIX: hỗ trợ nhánh superuser -- trước đây nhận tham số `tenant` và luôn filter
        tenant=tenant, khiến superuser (tenant=None) chỉ xóa được domain "tự do",
        không xóa được domain đã gán cho tenant nào.
        """
        try:
            if user.is_superuser:
                domain = Domain.objects.get(id=domain_id)
            else:
                domain = Domain.objects.get(id=domain_id, tenant=user.tenant)
        except Domain.DoesNotExist:
            raise ValidationError("Không tìm thấy tên miền hoặc bạn không có quyền thực hiện hành động xóa.")

        domain.delete()

    @staticmethod
    def get_list(user) -> list[Domain]:
        """Lấy danh sách các tên miền được quyền quản lý dựa theo phân quyền người dùng"""
        if user.is_superuser:
            return Domain.objects.all().order_by('-created_at')
        if not user.tenant:
            return Domain.objects.none()
        return Domain.objects.filter(tenant=user.tenant).order_by('-created_at')

    @staticmethod
    def get_detail(user, domain_id: int) -> Domain:
        """Xem chi tiết bản ghi thông tin của một tên miền cụ thể"""
        try:
            if user.is_superuser:
                return Domain.objects.get(id=domain_id)
            return Domain.objects.get(id=domain_id, tenant=user.tenant)
        except Domain.DoesNotExist:
            raise ValidationError("Tên miền không tồn tại hoặc bạn không có quyền truy cập thông tin dữ liệu này.")