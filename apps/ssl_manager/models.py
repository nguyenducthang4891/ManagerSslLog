from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core_networks.models import Domain
from django.conf import settings


class SSLCertificate(models.Model):
    STATUS_PENDING = "pending"
    STATUS_VALID = "valid"
    STATUS_INVALID = "invalid"
    STATUS_DEPLOYED = "deployed"
    STATUS_DEPLOYING = "deploying"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Đang xử lý"),
        (STATUS_VALID, "Hợp lệ"),
        (STATUS_INVALID, "Không hợp lệ"),
        (STATUS_DEPLOYED, "Đã deploy"),
        (STATUS_DEPLOYING, "Đang deploy"),
        (STATUS_FAILED, "Thất bại"),
    ]

    # Ngưỡng số ngày còn lại để coi là "sắp hết hạn" -- dùng cho is_expiring_soon.
    EXPIRY_WARNING_DAYS = 30

    name = models.CharField(max_length=255, verbose_name="Tên chứng chỉ")
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE, related_name="certificates", verbose_name="Domain")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    root_cert = models.FileField(upload_to="certificates/%Y/%m/", verbose_name="Root CA Certificate")
    inter_cert = models.FileField(upload_to="certificates/%Y/%m/", blank=True, null=True,
                                  verbose_name="Intermediate Certificate")
    server_cert = models.FileField(upload_to="certificates/%Y/%m/", verbose_name="Server Certificate")
    private_key = models.FileField(upload_to="certificates/%Y/%m/", verbose_name="Private Key")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    common_name = models.CharField(max_length=255, blank=True)
    issuer = models.CharField(max_length=500, blank=True)
    subject_alt_names = models.TextField(blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)

    validation_errors = models.TextField(blank=True)
    # Log của LẦN DEPLOY GẦN NHẤT (real-time, bị reset mỗi lần deploy mới).
    # Lịch sử đầy đủ từng lần deploy được lưu riêng ở model DeployHistory bên dưới.
    deploy_log = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deployed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "SSL Certificate"
        verbose_name_plural = "SSL Certificates"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} - {self.domain.name} ({self.status})"

    @property
    def is_expired(self):
        if self.valid_to:
            return self.valid_to < timezone.now()
        return False

    @property
    def days_until_expiry(self):
        if self.valid_to:
            delta = self.valid_to - timezone.now()
            return delta.days
        return None

    @property
    def is_expiring_soon(self):
        """
        True nếu cert còn hợp lệ (chưa hết hạn) nhưng số ngày còn lại <= ngưỡng
        cảnh báo (mặc định 30 ngày). Dùng để highlight cảnh báo trên cert_detail.html.
        """
        days = self.days_until_expiry
        if days is None:
            return False
        return 0 <= days <= self.EXPIRY_WARNING_DAYS

    def clean(self):
        super().clean()
        if self.uploaded_by and not self.uploaded_by.is_superuser:
            if self.domain.tenant != self.uploaded_by.tenant:
                raise ValidationError("Bạn không có quyền upload SSL cho domain thuộc tổ chức khác!")


class DeployHistory(models.Model):
    """
    MỚI: Lưu lịch sử TỪNG LẦN deploy riêng biệt, vì SSLCertificate.deploy_log
    chỉ giữ log của lần deploy gần nhất (bị reset mỗi lần deploy mới chạy --
    xem ZimbraDeployService.execute_deploy). Không có model này thì không thể
    xem lại các lần deploy thất bại trước đó sau khi đã deploy lại thành công.
    """
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Thành công"),
        (STATUS_FAILED, "Thất bại"),
    ]

    certificate = models.ForeignKey(
        SSLCertificate, on_delete=models.CASCADE, related_name="deploy_history",
        verbose_name="Chứng chỉ"
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        verbose_name="Người kích hoạt"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name="Kết quả")
    log_snapshot = models.TextField(blank=True, verbose_name="Toàn bộ log của lần deploy này")
    started_at = models.DateTimeField(verbose_name="Bắt đầu lúc")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Kết thúc lúc")

    class Meta:
        verbose_name = "Lịch sử Deploy"
        verbose_name_plural = "Lịch sử Deploy"
        ordering = ["-started_at"]

    def __str__(self):
        return f"Deploy #{self.id} - {self.certificate.name} ({self.status})"

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None