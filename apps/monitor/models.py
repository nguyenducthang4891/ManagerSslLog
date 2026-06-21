from django.db import models
from django.core.exceptions import ValidationError
from apps.tenants.models import Tenant
from apps.utils import EncryptedTextField


class ELKClusterConfig(models.Model):
    """
    Cấu hình kết nối tới 1 cụm Elasticsearch (chỉ cần HOST để kết nối).

    Mô hình thực tế:
    - Toàn hệ thống có 3 index CỐ ĐỊNH: metric, audit, mailbox. Tên index
      pattern KHÔNG khai báo ở model này -- đặt cứng trong code, mỗi loại
      log 1 file riêng (xem apps/monitor/services/metric.py, audit.py,
      mailbox.py và INDEX_PATTERN ở đầu mỗi file). Lý do: index pattern là
      hằng số toàn hệ thống, không đổi theo cluster/tenant, nên không cần
      thêm 1 bảng DB chỉ để lưu thứ không bao giờ thay đổi.
    - 1 Tenant chỉ dùng 1 HOST ELK duy nhất -- cả 3 index đều nằm trên host đó.
    - Bản ghi is_default=True là cụm ELK DÙNG CHUNG cho các tenant không có
      cấu hình riêng. Tenant nào cần host riêng (dedicated) thì tạo thêm
      bản ghi gán tenant=<tenant đó>.
    - Mỗi document trong cả 3 index đã có sẵn field tenant_code do AGENT tự
      gắn vào (xem ghi chú trong logstash/conf.d/metric.conf) -- nên dù
      nhiều tenant dùng CHUNG 1 host, việc lọc đúng phạm vi chỉ cần filter
      theo tenant_code (xem apps/monitor/services/base.py:base_filter).
    """
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, null=True, blank=True,
        related_name="elk_config",
        verbose_name="Tenant sở hữu (để trống nếu là cụm dùng chung)"
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name="Là cụm ELK dùng chung cho các Tenant không có cấu hình riêng"
    )

    name = models.CharField(max_length=100, verbose_name="Tên gợi nhớ")
    hosts = models.CharField(
        max_length=500,
        help_text="Danh sách host ES, phân tách bằng dấu phẩy. Ví dụ: https://es1:9200,https://es2:9200",
        verbose_name="Elasticsearch Hosts"
    )

    # Optional: chỉ điền nếu cụm ELK đó có bật xác thực (X-Pack security).
    username = models.CharField(max_length=150, blank=True, null=True, verbose_name="ES Username (tùy chọn)")
    password = EncryptedTextField(blank=True, null=True, verbose_name="ES Password (đã mã hóa, tùy chọn)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cấu hình cụm ELK"
        verbose_name_plural = "Cấu hình cụm ELK"

    def __str__(self):
        owner = "Dùng chung" if self.is_default else (self.tenant.name if self.tenant else "Chưa gán")
        return f"{self.name} ({owner})"

    def clean(self):
        super().clean()
        if self.is_default and self.tenant_id:
            raise ValidationError("Cụm ELK dùng chung (is_default=True) không được gán riêng cho Tenant nào.")
        if not self.is_default and not self.tenant_id:
            raise ValidationError("Cụm ELK không dùng chung thì phải gán cho một Tenant cụ thể.")

    def get_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.hosts.split(",") if h.strip()]

    def has_auth(self) -> bool:
        """True nếu cụm này được khai báo có username/password (optional)."""
        return bool(self.username and self.password)


class AlertThreshold(models.Model):
    """
    Ngưỡng cảnh báo tùy biến theo Tenant, CHỈ áp dụng cho index "metric"
    (override ngưỡng mặc định mà logstash/conf.d/metric.conf đã gắn sẵn
    lúc ingest). Không áp dụng cho audit/mailbox vì 2 index đó dùng tìm
    kiếm theo điều kiện (search), không có khái niệm "ngưỡng %".
    """
    METRIC_CPU = "cpu"
    METRIC_RAM = "ram"
    METRIC_DISK = "disk"
    METRIC_QUEUE = "queue"
    METRIC_CHOICES = [
        (METRIC_CPU, "CPU (%)"),
        (METRIC_RAM, "RAM (%)"),
        (METRIC_DISK, "Disk (%)"),
        (METRIC_QUEUE, "Mail Queue (số lượng)"),
    ]

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="alert_thresholds",
        verbose_name="Tenant"
    )
    metric = models.CharField(max_length=20, choices=METRIC_CHOICES, verbose_name="Chỉ số")
    warning_threshold = models.FloatField(verbose_name="Ngưỡng Warning")
    critical_threshold = models.FloatField(verbose_name="Ngưỡng Critical")

    class Meta:
        verbose_name = "Ngưỡng cảnh báo tùy biến"
        verbose_name_plural = "Ngưỡng cảnh báo tùy biến"
        unique_together = [("tenant", "metric")]

    def __str__(self):
        return f"{self.tenant.name} - {self.get_metric_display()} (W:{self.warning_threshold}/C:{self.critical_threshold})"

    def clean(self):
        super().clean()
        if self.warning_threshold >= self.critical_threshold:
            raise ValidationError("Ngưỡng Warning phải nhỏ hơn ngưỡng Critical.")