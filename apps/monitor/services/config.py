"""
apps/monitor/services/config.py
----------------------------------
Service CRUD cho 2 model cấu hình:
- ELKClusterConfig: CHỈ superuser được quản lý (host ELK là hạ tầng nhạy
  cảm -- ai cũng có thể sửa thì rủi ro trỏ sai/sai mật khẩu ảnh hưởng dữ
  liệu giám sát của tenant khác nếu lỡ tay sửa cụm dùng chung).
- AlertThreshold: superuser quản lý MỌI tenant; Tenant Admin chỉ quản lý
  ngưỡng cho CHÍNH tổ chức mình (giống pattern phân quyền đã dùng ở
  apps.tenants.services.TenantUserService.change_user_role).
"""
from django.core.exceptions import ValidationError
from apps.tenants.models import Tenant
from apps.monitor.models import ELKClusterConfig, AlertThreshold


class ELKClusterConfigService:
    """CRUD cấu hình host ELK -- chỉ superuser."""

    @staticmethod
    def _require_superuser(user):
        if not user.is_superuser:
            raise ValidationError("Chỉ Superadmin hệ thống mới có quyền quản lý cấu hình cụm ELK.")

    @staticmethod
    def get_list(user) -> list[ELKClusterConfig]:
        ELKClusterConfigService._require_superuser(user)
        return ELKClusterConfig.objects.select_related('tenant').order_by('-is_default', 'name')

    @staticmethod
    def get_detail(user, config_id: int) -> ELKClusterConfig:
        ELKClusterConfigService._require_superuser(user)
        try:
            return ELKClusterConfig.objects.select_related('tenant').get(id=config_id)
        except ELKClusterConfig.DoesNotExist:
            raise ValidationError("Không tìm thấy cấu hình cụm ELK chỉ định.")

    @staticmethod
    def create(user, name: str, hosts: str, is_default: bool,
               tenant_id: int | None = None, username: str = "", password: str = "") -> ELKClusterConfig:
        ELKClusterConfigService._require_superuser(user)

        if not name or not hosts:
            raise ValidationError("Tên gợi nhớ và Host ELK là bắt buộc.")

        tenant = None
        if not is_default:
            if not tenant_id:
                raise ValidationError("Cụm ELK không dùng chung thì phải chọn Tenant sở hữu.")
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise ValidationError("Tenant chỉ định không tồn tại.")
            if ELKClusterConfig.objects.filter(tenant=tenant).exists():
                raise ValidationError(f"Tổ chức '{tenant.name}' đã có cấu hình cụm ELK riêng. Vui lòng sửa bản ghi cũ.")
        else:
            if ELKClusterConfig.objects.filter(is_default=True).exists():
                raise ValidationError("Hệ thống đã có cụm ELK dùng chung. Vui lòng sửa bản ghi cũ thay vì tạo mới.")

        config = ELKClusterConfig(
            name=name.strip(),
            hosts=hosts.strip(),
            is_default=is_default,
            tenant=tenant,
            username=username.strip() or None,
            password=password or None,
        )
        config.full_clean()  # chạy clean() để validate is_default/tenant đồng bộ
        config.save()
        return config

    @staticmethod
    def update(user, config_id: int, **fields) -> ELKClusterConfig:
        ELKClusterConfigService._require_superuser(user)
        config = ELKClusterConfigService.get_detail(user, config_id)

        allowed_fields = ['name', 'hosts', 'username']
        update_fields = []
        for key, value in fields.items():
            if key not in allowed_fields:
                continue
            if value is None or value == "":
                continue
            setattr(config, key, value.strip() if isinstance(value, str) else value)
            update_fields.append(key)

        # password chỉ update khi người dùng thực sự nhập giá trị mới (không
        # ghi đè bằng rỗng -- giống cách ZimbraServerService.update_server xử lý
        # ssh_password để tránh xóa mất mật khẩu cũ khi form để trống).
        password = fields.get('password')
        if password:
            config.password = password
            update_fields.append('password')

        if update_fields:
            config.full_clean()
            config.save(update_fields=update_fields)
        return config

    @staticmethod
    def delete(user, config_id: int):
        ELKClusterConfigService._require_superuser(user)
        config = ELKClusterConfigService.get_detail(user, config_id)
        config.delete()


class AlertThresholdService:
    """
    CRUD ngưỡng cảnh báo theo tenant. Superuser quản lý mọi tenant;
    Tenant Admin chỉ quản lý ngưỡng của CHÍNH tổ chức mình.
    """

    @staticmethod
    def _resolve_target_tenant(acting_user, tenant_id: int | None) -> Tenant:
        """
        Superuser: phải truyền tenant_id rõ ràng (vì họ quản lý nhiều tenant).
        Tenant Admin: luôn bị ép về tenant của chính họ, bỏ qua tenant_id
        truyền vào nếu có (tránh họ tự ý sửa ngưỡng tổ chức khác bằng cách
        sửa tham số request).
        """
        if acting_user.is_superuser:
            if not tenant_id:
                raise ValidationError("Vui lòng chọn Tenant cần cấu hình ngưỡng.")
            try:
                return Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise ValidationError("Tenant chỉ định không tồn tại.")

        if acting_user.role != 'tenant_admin':
            raise ValidationError("Chỉ Tenant Admin hoặc Superuser mới có quyền cấu hình ngưỡng cảnh báo.")
        if not acting_user.tenant:
            raise ValidationError("Tài khoản của bạn không thuộc tổ chức nào.")
        return acting_user.tenant

    @staticmethod
    def get_list(acting_user, tenant_id: int | None = None) -> list[AlertThreshold]:
        """
        Superuser truyền tenant_id để xem ngưỡng của 1 tổ chức cụ thể (None
        = không lọc, xem tất cả). Tenant Admin luôn chỉ xem của tổ chức mình.
        """
        if acting_user.is_superuser:
            qs = AlertThreshold.objects.select_related('tenant')
            if tenant_id:
                qs = qs.filter(tenant_id=tenant_id)
            return qs.order_by('tenant__name', 'metric')

        if not acting_user.tenant:
            return AlertThreshold.objects.none()
        return AlertThreshold.objects.filter(tenant=acting_user.tenant).order_by('metric')

    @staticmethod
    def upsert(acting_user, metric: str, warning_threshold: float, critical_threshold: float,
               tenant_id: int | None = None) -> AlertThreshold:
        """
        Tạo mới hoặc cập nhật ngưỡng cho 1 metric cụ thể (unique_together đã
        đảm bảo mỗi tenant chỉ có 1 bản ghi / metric, nên dùng update_or_create
        thay vì phải phân biệt create/update ở tầng view).
        """
        target_tenant = AlertThresholdService._resolve_target_tenant(acting_user, tenant_id)

        valid_metrics = dict(AlertThreshold.METRIC_CHOICES)
        if metric not in valid_metrics:
            raise ValidationError("Chỉ số (metric) chỉ định không hợp lệ.")

        if warning_threshold >= critical_threshold:
            raise ValidationError("Ngưỡng Warning phải nhỏ hơn ngưỡng Critical.")

        threshold, _created = AlertThreshold.objects.update_or_create(
            tenant=target_tenant, metric=metric,
            defaults={"warning_threshold": warning_threshold, "critical_threshold": critical_threshold},
        )
        return threshold

    @staticmethod
    def delete(acting_user, threshold_id: int):
        """Xóa ngưỡng tùy biến -- sau khi xóa, metric đó rơi về DEFAULT_THRESHOLDS (xem services/metric.py)."""
        try:
            threshold = AlertThreshold.objects.select_related('tenant').get(id=threshold_id)
        except AlertThreshold.DoesNotExist:
            raise ValidationError("Không tìm thấy ngưỡng cảnh báo chỉ định.")

        if not acting_user.is_superuser:
            if acting_user.role != 'tenant_admin' or threshold.tenant_id != acting_user.tenant_id:
                raise ValidationError("Bạn không có quyền xóa ngưỡng cảnh báo của tổ chức khác.")

        threshold.delete()