"""
apps/monitor/services/backup.py
------------------------------------
Service riêng cho index "backup" (log-backup-*): giám sát kết quả backup
mailbox Zimbra (full + incremental) đẩy từ script backup_mailbox.sh ->
Filebeat -> Kafka (topic "backup") -> Logstash -> Elasticsearch.

Đi theo ĐÚNG khuôn mẫu với services/mailbox.py (4 bước: tenant scope, ELK
connection, time range + filter riêng, run_search) -- KHÁC BIỆT chính:
backup có thêm get_summary() để TỔNG HỢP (aggregation) số tài khoản đã
backup + tổng dung lượng trong khoảng thời gian, phục vụ đúng mục đích
ban đầu (thống kê theo ngày) -- KHÔNG thể suy ra từ query() phân trang
thông thường vì "total" của query() chỉ là tổng SỐ DÒNG LOG (1 account có
thể xuất hiện nhiều lần nếu inc chạy nhiều lượt/ngày), còn summary cần số
account DUY NHẤT (cardinality) + tổng size_bytes (sum) trên toàn bộ
index khớp điều kiện, không chỉ trang hiện tại.

GHI CHÚ MAPPING: áp dụng "match" (không phải "term") cho mọi field
categorical đến từ pipeline (backup_mode, status, tenant_code) -- giống lý
do đã nêu trong mailbox.py/audit.py: phòng trường hợp giá trị bị ghi dưới
dạng mảy 1 phần tử (vd: ["inc"]) tùy theo agent/phiên bản pipeline.
"""
from apps.tenants.models import Tenant
from apps.monitor.services.base import (
    ELKConnectionService, resolve_time_range, base_filter,
    require_tenant_scope, get_effective_tenant, run_search_paginated,
)

INDEX_PATTERN = "log-backup-*"

# Loại backup -- PHẢI khớp giá trị backup_mode mà logstash/conf.d/backup.conf
# sinh ra (full / inc). Dùng cho dropdown filter trên UI.
BACKUP_MODE_CHOICES = [
    ("full", "Full backup"),
    ("inc", "Incremental backup"),
]

# Trạng thái backup -- khớp field "status" do script backup_mailbox.sh ghi
# (SUCCESS / FAILED / NO_CONTENT). Dùng cho dropdown filter.
BACKUP_STATUS_CHOICES = [
    ("SUCCESS", "Thành công"),
    ("FAILED", "Thất bại"),
    ("NO_CONTENT", "Không có email mới"),
]

DEFAULT_PAGE_SIZE = 50


def _fix_tenant_filter(filter_: list, effective_tenant: Tenant | None) -> None:
    """
    Sửa điều kiện tenant_code do base_filter() sinh ra (đang dùng "term"
    trên "tenant_code.keyword") -- đổi sang "match" trên field gốc
    "tenant_code", giống cách mailbox.py/audit.py đã vá: phòng trường hợp
    giá trị được ghi dưới dạng mảy.
    """
    if effective_tenant is None:
        return
    for item in filter_:
        if "term" in item and "tenant_code.keyword" in item["term"]:
            tenant_val = item["term"]["tenant_code.keyword"]
            item.clear()
            item["match"] = {"tenant_code": tenant_val}


class BackupService:

    @staticmethod
    def query(user, tenant: Tenant | None = None,
              hours: int | None = None, days: int | None = None,
              date_from: str | None = None, date_to: str | None = None,
              backup_mode: str | None = None,
              status: str | None = None,
              search_account: str | None = None,
              page: int = 1,
              page_size: int = DEFAULT_PAGE_SIZE) -> dict:
        """
        search_account: tìm theo account (tên tài khoản mailbox đã backup)
        -- match (không phải term), khoan dung với mảy/không phân biệt
        hoa-thường do account luôn lowercase từ LDAP, nhưng vẫn chuẩn hóa
        ở đây để chắc chắn.

        date_from / date_to: filter "từ ngày - đến ngày" (chuỗi YYYY-MM-DD
        từ date picker trên UI) -- ƯU TIÊN hơn hours/days nếu có truyền
        vào (xem resolve_time_range trong base.py).

        page / page_size: phân trang THẬT qua "from"/"size" của ES (xem
        run_search_paginated trong base.py), giống mailbox.py -- dùng cho
        cơ chế "tải thêm khi kéo scroll" trên UI (monitor_backup.js).
        """
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        since, now = resolve_time_range(hours, days, date_from, date_to)
        filter_ = base_filter(effective_tenant, user.is_superuser, since, now)
        _fix_tenant_filter(filter_, effective_tenant)

        # "match" thay "term" cho backup_mode/status -- xem docstring đầu
        # file: khoan dung với giá trị dạng mảy do pipeline ghi vào.
        if backup_mode:
            filter_.append({"match": {"backup_mode": backup_mode}})

        if status:
            filter_.append({"match": {"status": status}})

        if search_account:
            filter_.append({"match": {"account": search_account.strip().lower()}})

        query_body = {"bool": {"filter": filter_}}

        hits, total = run_search_paginated(
            client, INDEX_PATTERN, query_body, cluster.name,
            page=page, page_size=page_size,
        )

        items = []
        for hit in hits:
            doc = hit["_source"]
            doc["_id"] = hit["_id"]
            items.append(doc)

        return {
            "total": total,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 1,
            "elk_cluster": cluster.name,
        }

    @staticmethod
    def get_summary(user, tenant: Tenant | None = None,
                     hours: int | None = None, days: int | None = None,
                     date_from: str | None = None, date_to: str | None = None,
                     backup_mode: str | None = None) -> dict:
        """
        Thống kê tổng hợp cho khoảng thời gian đã chọn -- ĐÚNG mục đích ban
        đầu (xem theo ngày backup được bao nhiêu tài khoản, tổng dung
        lượng bao nhiêu). Dùng Elasticsearch aggregations để tính TRÊN
        TOÀN BỘ index khớp điều kiện (không chỉ trang hiện tại), gồm:
            - success_count / failed_count / no_content_count: đếm theo
              "status" (terms aggregation theo từng giá trị).
            - unique_accounts_backed_up: SỐ TÀI KHOẢN DUY NHẤT đã có ít nhất 1 bản
              ghi SUCCESS trong khoảng thời gian (cardinality aggregation
              trên field "account") -- khác hẳn "total" của query(), vì 1 account
              có thể backup nhiều lần/ngày (full + inc chạy nhiều lượt) nên đếm
              dòng log không phản ánh đúng số tài khoản thực tế đã được backup.
            - total_size_bytes: TỔNG dung lượng (sum aggregation trên
              field "size_bytes", field số đã được Logstash chuẩn hóa từ
              chuỗi "4.0K"/"28K" sang bytes -- xem logstash/conf.d/backup.conf).

        ⭐ FIX: Không dùng runtime_mappings (quá phức tạp), thay vào đó
        dùng thẳng field từ Logstash đã normalize (status_norm, size_bytes).
        """
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        since, now = resolve_time_range(hours, days, date_from, date_to)
        filter_ = base_filter(effective_tenant, user.is_superuser, since, now)
        _fix_tenant_filter(filter_, effective_tenant)

        if backup_mode:
            filter_.append({"match": {"backup_mode": backup_mode}})

        query_body = {"bool": {"filter": filter_}}

        try:
            result = client.search(
                index=INDEX_PATTERN,
                query=query_body,
                size=0,  # Không cần lấy hits, chỉ cần kết quả aggregation.
                aggs={
                    # ⭐ Thống kê theo status -- dùng "status" field (đã normalize bởi Logstash)
                    "by_status": {
                        "terms": {
                            "field": "status",
                            "size": 10
                        }
                    },
                    # ⭐ Đếm số tài khoản DUYÊN NHẤT có status=SUCCESS
                    # (không phải đếm số dòng log -- mà đếm số account khác nhau)
                    "unique_accounts_success": {
                        "filter": {"term": {"status": "SUCCESS"}},
                        "aggs": {
                            "count": {"cardinality": {"field": "account"}}
                        },
                    },
                    # ⭐ Tổng dung lượng backup (bytes)
                    "total_size": {"sum": {"field": "size_bytes"}},
                },
            )
        except Exception as e:
            from django.core.exceptions import ValidationError
            raise ValidationError(f"Không thể truy vấn cụm ELK ({cluster.name}): {str(e)}")

        # ⭐ Xây dựng response từ aggregation results
        status_buckets = {b["key"]: b["doc_count"] for b in result["aggregations"]["by_status"]["buckets"]}
        unique_accounts = result["aggregations"]["unique_accounts_success"]["count"]["value"]
        total_size_bytes = result["aggregations"]["total_size"]["value"] or 0

        return {
            "success_count": status_buckets.get("SUCCESS", 0),
            "failed_count": status_buckets.get("FAILED", 0),
            "no_content_count": status_buckets.get("NO_CONTENT", 0),
            "unique_accounts_backed_up": unique_accounts,
            "total_size_bytes": int(total_size_bytes),
            "elk_cluster": cluster.name,
        }

    @staticmethod
    def get_log_detail(user, doc_id: str, tenant: Tenant | None = None) -> dict:
        """
        Lấy 1 document backup ĐẦY ĐỦ theo _id -- dùng cho modal xem JSON
        chi tiết. Vẫn áp tenant filter để chống user đoán _id tenant khác
        (defense-in-depth, giống mailbox.get_log_detail/audit.get_log_detail).
        """
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        filter_ = [{"ids": {"values": [doc_id]}}]

        if effective_tenant is not None:
            filter_.append({"match": {"tenant_code": effective_tenant.code.lower()}})

        hits, _total = run_search_paginated(
            client, INDEX_PATTERN, {"bool": {"filter": filter_}},
            cluster.name, page=1, page_size=1,
        )

        if not hits:
            return None

        doc = hits[0]["_source"]
        doc["_id"] = hits[0]["_id"]
        return doc