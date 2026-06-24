"""
apps/monitor/services/audit.py
------------------------------------
Service riêng cho index "audit" (log-audit-*): nhật ký hành động quản trị
Zimbra (đăng nhập, tạo/sửa/xóa account, đổi mật khẩu...). Đi theo cùng
khuôn mẫu với services/metric.py (4 bước: tenant scope, ELK connection,
time range + filter riêng, run_search) -- KHÁC BIỆT chính: audit KHÔNG có
khái niệm severity/threshold (%) như metric, vì đây là log dạng "có xảy ra
hay không", không phải chỉ số liên tục.
"""
from apps.tenants.models import Tenant
from apps.monitor.services.base import (
    ELKConnectionService, resolve_time_range, base_filter,
    require_tenant_scope, get_effective_tenant, run_search_paginated,
)

INDEX_PATTERN = "log-audit-*"

# Field hiển thị cho dropdown filter "Phân loại hành động" trên UI -- PHẢI
# khớp với các giá trị action_category mà conf.d/audit.conf sinh ra.
ACTION_CATEGORY_CHOICES = [
    ("authentication", "Đăng nhập / Xác thực"),
    ("account_management", "Quản lý tài khoản"),
    ("password_management", "Quản lý mật khẩu"),
    ("domain_management", "Quản lý Domain"),
    ("distribution_list", "Danh sách phân phối"),
    ("cos_management", "Class of Service (COS)"),
    ("system_management", "Quản trị hệ thống"),
    ("mailbox_management", "Quản lý Mailbox"),
    ("other", "Khác"),
]


class AuditService:

    @staticmethod
    def query(user, tenant: Tenant | None = None,
              hours: int | None = None, days: int | None = None,
              action_category: str | None = None,
              keyword: str | None = None,
              page: int = 1,
              page_size: int = 50) -> dict:
        """
        keyword: tìm theo admin_email HOẶC auth_email (ai thực hiện hành
        động) -- dùng "should" để khớp 1 trong 2, vì với hành động "Auth"
        (đăng nhập) 2 field này thường trùng nhau, nhưng với hành động 1
        admin sửa tài khoản người khác thì admin_email (người thực hiện)
        khác target_email (người bị tác động) -- người dùng quan tâm "AI
        đã làm" nên ưu tiên admin_email/auth_email, không phải target_email.

        page / page_size: phân trang THẬT qua "from"/"size" của ES (xem
        run_search_paginated trong base.py) -- dùng cho cơ chế "tải thêm
        khi kéo scroll" trên UI (monitor_audit.js), KHÁC với hành vi cũ là
        luôn lấy 1 lần page_size bản ghi đầu tiên rồi dừng. Trả thêm
        "total" là tổng số bản ghi khớp điều kiện trên TOÀN BỘ index, để
        UI biết khi nào đã tải hết (không còn trang để load thêm).
        """
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        since, now = resolve_time_range(hours, days)

        # Lấy bộ lọc cơ bản (bao gồm thời gian và tenant)
        filter_ = base_filter(effective_tenant, user.is_superuser, since, now)

        # 🌟 VÁ LỖI 1: Nếu trong base_filter() của bạn đang dùng {"term": {"tenant_code.keyword": ...}}
        # và bị fail do dữ liệu dạng mảng, ta duyệt qua filter_ để tối ưu hóa nó sang dạng match/term phẳng.
        for item in filter_:
            if "term" in item and "tenant_code.keyword" in item["term"]:
                tenant_val = item["term"]["tenant_code.keyword"]
                # Đổi hẳn sang ép match trường tenant_code gốc để bóc tách mảng ["cto"] dễ dàng
                item.clear()
                item["match"] = {"tenant_code": tenant_val}

        # 🌟 VÁ LỖI 2: Đổi từ "term" sang "match" cho action_category để xử lý mảng dữ liệu ["authentication"]
        if action_category:
            filter_.append({"match": {"action_category": action_category}})

        query_body = {"bool": {"filter": filter_}}

        if keyword:
            # match trên keyword field (exact theo từng giá trị email, ES
            # vẫn cho phép "match" trên field type keyword -- hoạt động như
            # term nhưng cho phép OR qua "should" tự nhiên hơn so với term).
            query_body["bool"]["should"] = [
                {"term": {"admin_email": keyword.strip().lower()}},
                {"term": {"auth_email": keyword.strip().lower()}},
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
        Lấy 1 document audit ĐẦY ĐỦ theo _id -- dùng cho modal "xem log
        gốc". Vẫn phải áp tenant filter để chống user đoán _id của tenant
        khác (dù _id khó đoán, đây là lớp bảo vệ defense-in-depth, không
        tin tưởng riêng _id làm cơ chế phân quyền).
        """
        require_tenant_scope(user)
        effective_tenant = get_effective_tenant(user, tenant)

        cluster = ELKConnectionService.get_config_for_tenant(effective_tenant)
        client = ELKConnectionService.get_client(cluster)

        filter_ = [{"ids": {"values": [doc_id]}}]

        # 🌟 VÁ LỖI 3: Đồng bộ hóa hàm lấy chi tiết bằng match query cho mảng tenant_code
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