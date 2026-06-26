"""
apps/monitor/services/mailbox.py
------------------------------------
Service riêng cho index "mailbox" (log-mailbox-*): giám sát thư đi/đến qua
hệ thống Zimbra (amavis + postfix smtp/lmtp/qmgr/cleanup/bounce). Đi theo
đúng khuôn mẫu với services/metric.py và services/audit.py (4 bước: tenant
scope, ELK connection, time range + filter riêng, run_search).

GHI CHÚ MAPPING QUAN TRỌNG: dù index template (log-mailbox-template.json)
khai "tenant_code", "mail_direction", "status" đều là kiểu "keyword" NGAY
TỪ ĐẦU, thực tế đã quan sát được (xem báo lỗi: chọn mail_direction=INTERNAL
-> rỗng, nhưng không chọn gì thì danh sách vẫn có bản ghi INTERNAL) cho
thấy các field categorical này có thể được agent/Kafka ghi vào dưới dạng
MẢNG một phần tử (vd: ["INTERNAL"]) tương tự tenant_code/action_category
mà audit.py đã từng gặp và phải vá lại.

"term" trên 1 keyword field VẪN khớp đúng với mảng 1 phần tử trong hầu hết
trường hợp -- nhưng để AN TOÀN TUYỆT ĐỐI (không phụ thuộc agent có ghi
field này nhất quán giữa các phiên bản pipeline khác nhau hay không), ta
CHỦ ĐỘNG dùng "match" cho mọi field categorical đến từ pipeline (gồm
mail_direction, status, tenant_code) -- "match" trên keyword field hoạt
động giống "term" (so khớp chính xác, không phân tích/tokenize) nhưng
khoan dung hơn với cấu trúc mảng/giá trị lồng nhau, đúng cách audit.py đã
áp dụng cho action_category và tenant_code.
"""
from apps.tenants.models import Tenant
from apps.monitor.services.base import (
    ELKConnectionService, resolve_time_range, base_filter,
    require_tenant_scope, get_effective_tenant, run_search_paginated,
)

INDEX_PATTERN = "log-mailbox-*"

# Chiều thư -- PHẢI khớp giá trị mail_direction mà logstash.conf (mailbox)
# sinh ra ở BƯỚC 12.5 (INTERNAL / OUTBOUND / INBOUND / EXTERNAL /
# BOUNCE_SYSTEM). Dùng cho dropdown filter trên UI.
MAIL_DIRECTION_CHOICES = [
    ("INTERNAL", "Nội bộ (Internal)"),
    ("OUTBOUND", "Gửi đi (Outbound)"),
    ("INBOUND", "Nhận về (Inbound)"),
    ("EXTERNAL", "Ngoài hệ thống (External)"),
    ("BOUNCE_SYSTEM", "Hệ thống trả thư (Bounce)"),
]

# Trạng thái gửi -- khớp field "status" sinh ra từ grok pattern
# postfix/smtp|lmtp (sent/deferred/bounced). Dùng cho dropdown filter.
MAIL_STATUS_CHOICES = [
    ("sent", "Đã gửi (Sent)"),
    ("deferred", "Tạm hoãn (Deferred)"),
    ("bounced", "Bị trả lại (Bounced)"),
]

DEFAULT_PAGE_SIZE = 50


def _fix_tenant_filter(filter_: list, effective_tenant: Tenant | None) -> None:
    """
    Sửa điều kiện tenant_code do base_filter() sinh ra (đang dùng "term"
    trên "tenant_code.keyword") -- đổi sang "match" trên field gốc
    "tenant_code", giống lý do nêu trong docstring đầu file: phòng trường
    hợp giá trị được ghi dưới dạng mảng, "match" khoan dung hơn "term".
    """
    if effective_tenant is None:
        return
    for item in filter_:
        if "term" in item and "tenant_code.keyword" in item["term"]:
            tenant_val = item["term"]["tenant_code.keyword"]
            item.clear()
            item["match"] = {"tenant_code": tenant_val}


class MailboxService:

    @staticmethod
    def query(user, tenant: Tenant | None = None,
              hours: int | None = None, days: int | None = None,
              date_from: str | None = None, date_to: str | None = None,
              mail_direction: str | None = None,
              status: str | None = None,
              search_email: str | None = None,
              page: int = 1,
              page_size: int = DEFAULT_PAGE_SIZE) -> dict:
        """
        search_email: tìm theo from HOẶC to (người dùng không cần biết là
        thư đi hay đến, chỉ cần biết "có liên quan tới địa chỉ X" -- dùng
        "should" để khớp 1 trong 2 field, giống cách audit.py xử lý
        admin_email/auth_email).

        date_from / date_to: filter "từ ngày - đến ngày" (chuỗi YYYY-MM-DD
        từ date picker trên UI) -- ƯU TIÊN hơn hours/days nếu có truyền
        vào (xem resolve_time_range trong base.py), giống cách backup.py
        đang dùng.

        page / page_size: phân trang THẬT qua "from"/"size" của ES (xem
        run_search_paginated trong base.py) -- KHÁC với cách audit.py/
        metric.py đang làm (luôn lấy 1 lần "page_size" bản ghi đầu, không
        có khái niệm trang). Trả thêm "total" là tổng số bản ghi khớp điều
        kiện trên TOÀN BỘ index, để UI tính được tổng số trang.
        """
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        since, now = resolve_time_range(hours, days, date_from, date_to)
        filter_ = base_filter(effective_tenant, user.is_superuser, since, now)
        _fix_tenant_filter(filter_, effective_tenant)

        # "match" thay "term" cho mail_direction/status -- xem docstring
        # đầu file: khoan dung với giá trị dạng mảng do pipeline ghi vào,
        # đây chính là nguyên nhân thực tế gây ra bug "chọn INTERNAL ->
        # rỗng" khi còn dùng "term".
        if mail_direction:
            filter_.append({"match": {"mail_direction": mail_direction}})

        if status:
            filter_.append({"match": {"status": status}})

        query_body = {"bool": {"filter": filter_}}

        if search_email:
            email_norm = search_email.strip().lower()
            query_body["bool"]["should"] = [
                {"match": {"from": email_norm}},
                {"match": {"to": email_norm}},
            ]
            query_body["bool"]["minimum_should_match"] = 1

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
    def get_log_detail(user, doc_id: str, tenant: Tenant | None = None) -> dict:
        """
        Lấy 1 document mailbox ĐẦY ĐỦ theo _id -- dùng cho modal xem JSON
        chi tiết. Vẫn áp tenant filter để chống user đoán _id tenant khác
        (defense-in-depth, giống audit.get_log_detail).
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