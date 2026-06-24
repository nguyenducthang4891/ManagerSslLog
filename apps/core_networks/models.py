from django.db import models
from apps.tenants.models import Tenant
from apps.utils import EncryptedTextField


class ZimbraServer(models.Model):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="servers", verbose_name="Dedicated Tenant (Nếu có)"
    )
    name = models.CharField(max_length=100, verbose_name="Tên server")
    hostname = models.CharField(max_length=255, verbose_name="Hostname/IP")
    port = models.IntegerField(default=22, verbose_name="SSH Port")
    username = models.CharField(max_length=100, default="root", verbose_name="SSH User")

    # Các trường nhạy cảm: mã hóa tại field-level, không bao giờ render lại nguyên giá trị ra client.
    ssh_password = EncryptedTextField(blank=True, verbose_name="SSH Password (đã mã hóa)")
    ssh_key = EncryptedTextField(blank=True, verbose_name="SSH Private Key (đã mã hóa)")
    zimbra_admin_email = models.EmailField(help_text="Ví dụ: admin@yourdomain.com", null=True, blank=True)
    zimbra_admin_password = EncryptedTextField(blank=True, null=True, verbose_name="Zimbra Admin Password (đã mã hóa)")

    zimbra_home = models.CharField(max_length=255, default="/opt/zimbra", verbose_name="Zimbra Home")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Zimbra Server"
        verbose_name_plural = "Zimbra Servers"

    def __str__(self):
        return f"{self.name} ({self.hostname})"


class Domain(models.Model):
    # FIX: default=True là sai kiểu cho ForeignKey (Django sẽ cố lưu True làm tenant_id).
    # Domain "tự do" (chưa gán tổ chức) được biểu diễn bằng tenant = None, không cần default.
    tenant = models.ForeignKey(
        Tenant, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="domains", verbose_name="Tổ chức "
    )
    name = models.CharField(max_length=255, unique=True, verbose_name="Tên Miền (ví dụ: domain.com)")
    server = models.ForeignKey(
        ZimbraServer, on_delete=models.PROTECT, related_name="domains",
        verbose_name="Máy chủ Email"
    )
    is_active = models.BooleanField(default=True, verbose_name="Kích hoạt")
    created_at = models.DateTimeField(auto_now_add=True)
    is_created_on_zimbra = models.BooleanField(
        default=True,
        verbose_name="Khởi tạo trên máy chủ Email",
        help_text="Nếu không chọn, Tên miền sẽ ko tạo trên máy chủ Email"
    )
    class Meta:
        verbose_name = "Domain"
        verbose_name_plural = "Domains"

    def __str__(self):
        tenant_name = self.tenant.name if self.tenant else "Chưa gán"
        return f"{self.name} ({tenant_name})"