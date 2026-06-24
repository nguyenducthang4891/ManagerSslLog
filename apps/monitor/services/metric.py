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
    require_tenant_scope, get_effective_tenant, run_search, run_search_paginated,
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


def _build_severity_clause(thresholds: dict, level: str) -> dict:
    """
    Dựng điều kiện ES (bool "should", khớp 1 trong nhiều) tương đương với
    logic _recompute_severity() ở trên, NHƯNG chạy ngay trên Elasticsearch
    (range query trên field numeric) thay vì tính bằng Python sau khi đã
    lấy hits -- điều kiện BẮT BUỘC để có thể phân trang ES thật (from/size
    + track_total_hits) một cách CHÍNH XÁC, vì ES cần biết "khớp hay
    không" cho MỌI document trong index, không chỉ trang hiện tại.

    level="critical": zimbra_not_running_count > 0 HOẶC cpu/ram/disk/queue
                       vượt ngưỡng critical (so theo đúng thứ tự nhánh đầu
                       tiên của _recompute_severity()).
    level="warning":  cpu/ram/disk/queue vượt ngưỡng warning (chưa loại
                       trừ critical -- việc loại trừ critical được ghép ở
                       _build_severity_filter() bên dưới bằng "must_not").
    """
    cpu_t = thresholds[AlertThreshold.METRIC_CPU]
    ram_t = thresholds[AlertThreshold.METRIC_RAM]
    disk_t = thresholds[AlertThreshold.METRIC_DISK]
    queue_t = thresholds[AlertThreshold.METRIC_QUEUE]

    if level == "critical":
        return {
            "bool": {
                "should": [
                    {"range": {"zimbra_not_running_count": {"gt": 0}}},
                    {"range": {"cpu": {"gte": cpu_t["critical"]}}},
                    {"range": {"ram": {"gte": ram_t["critical"]}}},
                    {"range": {"disk": {"gte": disk_t["critical"]}}},
                    {"range": {"queue": {"gte": queue_t["critical"]}}},
                ],
                "minimum_should_match": 1,
            }
        }
    elif level == "warning":
        return {
            "bool": {
                "should": [
                    {"range": {"cpu": {"gte": cpu_t["warning"]}}},
                    {"range": {"ram": {"gte": ram_t["warning"]}}},
                    {"range": {"disk": {"gte": disk_t["warning"]}}},
                    {"range": {"queue": {"gte": queue_t["warning"]}}},
                ],
                "minimum_should_match": 1,
            }
        }
    raise ValueError(f"level không hợp lệ: {level}")


def _apply_severity_filter(query_body: dict, thresholds: dict, severity_filter: str) -> None:
    """
    Áp điều kiện severity_filter ("ok"/"warning"/"critical") TRỰC TIẾP vào
    query_body (mutate in-place) -- để ES tự lọc đúng theo severity NGAY
    TRONG QUERY, thay vì lọc bằng Python sau khi đã có hits (cách cũ trong
    MetricService.query(), không tương thích với phân trang ES thật).

    "ok"        = NOT critical AND NOT warning
    "warning"   = NOT critical AND warning
    "critical"  = critical (đã bao trùm, không cần loại gì thêm)
    """
    critical_clause = _build_severity_clause(thresholds, "critical")
    warning_clause = _build_severity_clause(thresholds, "warning")

    bool_query = query_body["bool"]
    bool_query.setdefault("must_not", [])
    bool_query.setdefault("filter", [])

    if severity_filter == "critical":
        bool_query["filter"].append(critical_clause)
    elif severity_filter == "warning":
        bool_query["must_not"].append(critical_clause)
        bool_query["filter"].append(warning_clause)
    elif severity_filter == "ok":
        bool_query["must_not"].append(critical_clause)
        bool_query["must_not"].append(warning_clause)


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
            # FIX: chuẩn hoá lowercase trước khi term-match trên
            # "hostname.keyword". Term query không tokenize, nên khớp
            # TUYỆT ĐỐI theo giá trị gốc đã index -- nếu user gõ hoa/thường
            # khác với giá trị lưu trong ES (luôn lowercase, theo agent),
            # query sẽ trả về rỗng dù dữ liệu thực sự tồn tại. Lowercase ở
            # đây khớp với cách agent ghi field "hostname" (xem sample log
            # gốc: "hostname": "ldap.cantho.gov.vn" -- luôn lowercase).
            filter_.append({"term": {"hostname.keyword": hostname.strip().lower()}})

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
    def query_paginated(user, tenant: Tenant | None = None,
                         hours: int | None = None, days: int | None = None,
                         severity_filter: str | None = None,
                         hostname: str | None = None,
                         page: int = 1,
                         page_size: int = 50) -> dict:
        """
        Bản PHÂN TRANG THẬT của query() -- dùng cho metric_detail.html
        (infinite scroll). KHÔNG thay thế query() (vẫn giữ nguyên cho
        metric.html/api_query_metric, không ảnh hưởng gì).

        KHÁC BIỆT CỐT LÕI: severity_filter được đẩy XUỐNG ES dưới dạng
        range query theo threshold (xem _apply_severity_filter()), KHÔNG
        lọc bằng Python sau khi lấy hits -- nên "total" trả về CHÍNH XÁC
        100% trên toàn bộ index khớp điều kiện (kể cả khi có severity_filter),
        và "from"/"size" phân trang đúng từng trang, không cần re-fetch lại
        từ đầu mỗi lần tải thêm.
        """
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        since, now = resolve_time_range(hours, days)
        filter_ = base_filter(effective_tenant, user.is_superuser, since, now)
        if hostname:
            filter_.append({"term": {"hostname.keyword": hostname.strip().lower()}})

        query_body = {"bool": {"filter": filter_}}

        thresholds = _get_tenant_thresholds(effective_tenant)
        if severity_filter:
            _apply_severity_filter(query_body, thresholds, severity_filter)

        hits, total = run_search_paginated(
            client, INDEX_PATTERN, query_body, cluster.name,
            page=page, page_size=page_size,
        )

        items = []
        for hit in hits:
            doc = hit["_source"]
            doc["severity"] = _recompute_severity(doc, thresholds)
            doc["_id"] = hit["_id"]
            items.append(doc)

        return {
            "total": total,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 1,
            "thresholds": thresholds,
            "elk_cluster": cluster.name,
        }

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