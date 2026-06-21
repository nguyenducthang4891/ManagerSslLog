"""
apps/monitor/services/metric.py
------------------------------------
Service riêng cho index "metric" (server-metrics-*): CPU/RAM/Disk/Zimbra
service + tính lại severity theo ngưỡng tùy biến của tenant.

Đây là khuôn mẫu để viết audit.py / mailbox.py: mọi service riêng đều có
cùng 4 bước:
    1. require_tenant_scope(user) + get_effective_tenant(user, tenant)
    2. ELKConnectionService.get_config_for_tenant() + get_client()
    3. resolve_time_range() + base_filter() + filter riêng của loại log này
    4. run_search() rồi tự xử lý _source theo field riêng
"""
from apps.tenants.models import Tenant
from apps.monitor.models import AlertThreshold
from apps.monitor.services.base import (
    ELKConnectionService, resolve_time_range, base_filter,
    require_tenant_scope, get_effective_tenant, run_search,
)

INDEX_PATTERN = "log-metrics-*"

# Ngưỡng mặc định toàn hệ thống -- PHẢI khớp với logic trong
# logstash/conf.d/metric.conf (dùng làm fallback khi tenant không có
# AlertThreshold riêng).
DEFAULT_THRESHOLDS = {
    AlertThreshold.METRIC_CPU:   {"warning": 75, "critical": 90},
    AlertThreshold.METRIC_RAM:   {"warning": 80, "critical": 90},
    AlertThreshold.METRIC_DISK:  {"warning": 80, "critical": 90},
    AlertThreshold.METRIC_QUEUE: {"warning": 100, "critical": 500},
}

SEVERITY_ORDER = {"ok": 0, "warning": 1, "critical": 2}


def _get_tenant_thresholds(tenant: Tenant | None) -> dict:
    thresholds = {k: dict(v) for k, v in DEFAULT_THRESHOLDS.items()}
    if tenant:
        for t in AlertThreshold.objects.filter(tenant=tenant):
            thresholds[t.metric] = {"warning": t.warning_threshold, "critical": t.critical_threshold}
    return thresholds


def _recompute_severity(doc: dict, thresholds: dict) -> str:
    if doc.get("zimbra_not_running_count", 0) > 0:
        return "critical"

    severity = "ok"
    checks = [
        (AlertThreshold.METRIC_CPU, doc.get("cpu", 0)),
        (AlertThreshold.METRIC_RAM, doc.get("ram", 0)),
        (AlertThreshold.METRIC_DISK, doc.get("disk", 0)),
        (AlertThreshold.METRIC_QUEUE, doc.get("queue", 0)),
    ]
    for metric, value in checks:
        t = thresholds[metric]
        if value >= t["critical"]:
            return "critical"
        elif value >= t["warning"] and SEVERITY_ORDER[severity] < SEVERITY_ORDER["warning"]:
            severity = "warning"
    return severity


class MetricService:

    @staticmethod
    def query(user, tenant: Tenant | None = None,
              hours: int | None = None, days: int | None = None,
              severity_filter: str | None = None,
              hostname: str | None = None,
              page_size: int = 200) -> dict:
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        since, now = resolve_time_range(hours, days)
        filter_ = base_filter(effective_tenant, user.is_superuser, since, now)
        if hostname:
            # FIX: dùng .keyword vì mapping thật của field "hostname" trên ES
            # là kiểu "text" (xem ghi chú chi tiết trong base_filter() ở base.py).
            filter_.append({"term": {"hostname.keyword": hostname}})

        hits = run_search(client, INDEX_PATTERN, {"bool": {"filter": filter_}},
                           cluster.name, size=page_size)

        thresholds = _get_tenant_thresholds(effective_tenant)
        items = []
        for hit in hits:
            doc = hit["_source"]
            doc["severity"] = _recompute_severity(doc, thresholds)
            doc["_id"] = hit["_id"]
            items.append(doc)

        if severity_filter:
            items = [d for d in items if d["severity"] == severity_filter]

        return {"total": len(items), "items": items, "thresholds": thresholds, "elk_cluster": cluster.name}

    @staticmethod
    def get_alert_summary(user, tenant: Tenant | None = None, hours: int = 24) -> dict:
        data = MetricService.query(user, tenant=tenant, hours=hours)
        warning_count = sum(1 for d in data["items"] if d["severity"] == "warning")
        critical_count = sum(1 for d in data["items"] if d["severity"] == "critical")
        return {
            "total_samples": data["total"],
            "warning_count": warning_count,
            "critical_count": critical_count,
            "elk_cluster": data.get("elk_cluster"),
        }