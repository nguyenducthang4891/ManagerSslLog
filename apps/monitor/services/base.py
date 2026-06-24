"""
apps/monitor/services/base.py
---------------------------------
Logic DÙNG CHUNG cho mọi loại log (metric/audit/mailbox và bất kỳ loại nào
thêm sau này). Mỗi service riêng (metric.py, audit.py, mailbox.py) import
từ đây để không lặp lại:
    - Cách chọn cụm ELK (host) theo tenant
    - Cách filter theo tenant_code (cô lập dữ liệu khi nhiều tenant dùng
      chung 1 host)
    - Cách resolve khoảng thời gian (hours/days)

Khi viết service cho loại log thứ 4 (nếu sau này có), chỉ cần:
    from apps.monitor.services.base import (
        ELKConnectionService, resolve_time_range, base_filter, require_tenant_scope,
        get_effective_tenant,
    )
và viết thêm 1 file mới theo khuôn của metric.py/audit.py.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from elasticsearch import Elasticsearch
from apps.tenants.models import Tenant
from apps.monitor.models import ELKClusterConfig

# Tên field timestamp dùng để lọc theo giờ/ngày -- GIỐNG NHAU cho mọi index,
# vì mọi pipeline Logstash đều chuẩn hóa timestamp gốc về @timestamp
# (xem bước "1. Chuẩn hóa timestamp" trong cả 3 file logstash/conf.d/*.conf).
TIMESTAMP_FIELD = "@timestamp"


class ELKConnectionService:
    """
    Quyết định cụm ELK (host) nào dùng cho 1 Tenant: ưu tiên cấu hình riêng
    của tenant đó, nếu không có thì rơi về cụm dùng chung (is_default=True).
    Auth là OPTIONAL -- chỉ truyền nếu cluster có khai username/password.

    Dùng CHUNG cho mọi loại log, vì 1 tenant chỉ có 1 host ELK duy nhất cho
    cả 3 index metric/audit/mailbox (đã chốt yêu cầu).
    """

    @staticmethod
    def get_config_for_tenant(tenant: Tenant | None) -> ELKClusterConfig:
        if tenant is not None:
            dedicated = ELKClusterConfig.objects.filter(tenant=tenant).first()
            if dedicated:
                return dedicated

        default_config = ELKClusterConfig.objects.filter(is_default=True).first()
        if not default_config:
            raise ValidationError(
                "Hệ thống chưa cấu hình cụm ELK dùng chung (is_default=True). "
                "Vui lòng khai báo trong phần Cấu hình ELK."
            )
        return default_config

    @staticmethod
    def get_client(cluster: ELKClusterConfig) -> Elasticsearch:
        kwargs = {}
        if cluster.has_auth():
            kwargs["basic_auth"] = (cluster.username, cluster.password)
        return Elasticsearch(cluster.get_hosts_list(), **kwargs)


def resolve_time_range(hours: int | None, days: int | None) -> tuple:
    """Trả về (since, now). Mặc định 24h gần nhất nếu không truyền gì."""
    now = timezone.now()
    if hours:
        since = now - timedelta(hours=hours)
    elif days:
        since = now - timedelta(days=days)
    else:
        since = now - timedelta(hours=24)
    return since, now


def require_tenant_scope(user):
    """Chặn sớm nếu user không thuộc tổ chức nào và không phải superuser."""
    if not user.is_superuser and not user.tenant:
        raise ValidationError("Tài khoản không thuộc tổ chức nào, không có dữ liệu giám sát.")


def get_effective_tenant(user, tenant: Tenant | None) -> Tenant | None:
    """Superuser có thể truyền tenant cụ thể để xem; non-superuser luôn bị ép về tenant của mình."""
    return tenant if user.is_superuser else user.tenant


def base_filter(effective_tenant: Tenant | None, is_superuser: bool, since, now) -> list:
    """
    Filter ES dùng chung cho MỌI index: khoảng thời gian + cô lập theo
    tenant_code (field có sẵn trong mọi document, do agent tự gắn vào).

    - Có effective_tenant -> luôn filter đúng tenant_code đó (áp dụng cả
      cho superuser khi họ chọn xem 1 tenant cụ thể).
    - Không có effective_tenant + là superuser -> xem tất cả tenant (không
      filter tenant_code).
    - Không có effective_tenant + KHÔNG phải superuser -> lỗi (lớp bảo vệ
      thứ 2, vì require_tenant_scope() đã chặn từ trước).

    LƯU Ý MAPPING (đã xác nhận thực tế trên cụm ES của dự án): nếu index
    được tạo TRƯỚC KHI index template trong logstash/index-templates/*.json
    được áp dụng, Elasticsearch sẽ tự suy luận "tenant_code" là kiểu "text"
    (full-text, có phân tích/tokenize), KHÔNG phải "keyword" như mong muốn.
    "term" query trên field "text" hầu như luôn không khớp vì giá trị đã bị
    analyzer biến đổi lúc index. Vì vậy PHẢI filter trên sub-field
    "tenant_code.keyword" (ES tự tạo sẵn sub-field này theo dynamic mapping
    mặc định) để so khớp đúng giá trị gốc, bất kể mapping field cha là gì.
    Dùng .keyword ở đây an toàn cho cả 2 trường hợp: nếu sau này mapping
    field cha đã đúng "keyword" ngay từ đầu, ES vẫn tự tạo sẵn sub-field
    .keyword giống vậy (theo dynamic mapping chuẩn), nên không cần sửa lại.
    """
    filter_ = [{"range": {TIMESTAMP_FIELD: {"gte": since.isoformat(), "lte": now.isoformat()}}}]
    if effective_tenant is not None:
        filter_.append({"term": {"tenant_code.keyword": effective_tenant.code.lower()}})
    elif not is_superuser:
        raise ValidationError("Không xác định được phạm vi tổ chức để truy vấn.")
    return filter_


def run_search(client: Elasticsearch, index_pattern: str, query: dict,
                cluster_name: str, sort_field: str = TIMESTAMP_FIELD,
                size: int = 200) -> list:
    """
    Helper chạy search + bắt lỗi thống nhất (1 chỗ raise ValidationError với
    message tiếng Việt rõ ràng, thay vì mỗi service tự viết try/except riêng).
    Trả về danh sách hit thô (chưa xử lý _source) -- mỗi service tự quyết
    định cách xử lý field riêng của mình.

    LƯU Ý: hàm này KHÔNG hỗ trợ phân trang thật (luôn lấy "size" bản ghi
    đầu tiên từ đầu) -- giữ nguyên để không phá vỡ metric.py/audit.py đang
    dùng. Cho nhu cầu phân trang (vd: mailbox.py), dùng run_search_paginated()
    bên dưới.
    """
    try:
        result = client.search(
            index=index_pattern,
            query=query,
            sort=[{sort_field: {"order": "desc"}}],
            size=size,
        )
    except Exception as e:
        raise ValidationError(f"Không thể truy vấn cụm ELK ({cluster_name}): {str(e)}")
    return result["hits"]["hits"]


def run_search_paginated(client: Elasticsearch, index_pattern: str, query: dict,
                          cluster_name: str, sort_field: str = TIMESTAMP_FIELD,
                          page: int = 1, page_size: int = 50) -> tuple:
    """
    Giống run_search() nhưng hỗ trợ PHÂN TRANG THẬT qua "from"/"size" của
    Elasticsearch, và trả về TỔNG SỐ BẢN GHI THỰC TẾ khớp điều kiện lọc
    (không phải chỉ số lượng bản ghi trong trang hiện tại).

    Dùng "track_total_hits=True" để buộc ES đếm CHÍNH XÁC tổng số hit, vì
    mặc định ES chỉ đếm chính xác tới 10.000 rồi báo "gte" (giá trị gần
    đúng, có thể đánh lừa UI hiển thị sai tổng số trang) -- với khối lượng
    log mailbox tích lũy nhiều ngày, số bản ghi khớp điều kiện lọc rộng
    (vd: không lọc gì, khoảng thời gian dài) có thể vượt 10.000 dễ dàng.

    page: 1-indexed (trang 1 là trang đầu tiên, không phải trang 0).

    Trả về: (hits, total) -- hits là danh sách hit thô của TRANG HIỆN TẠI,
    total là tổng số bản ghi khớp điều kiện trên TOÀN BỘ index (không chỉ
    trang hiện tại).
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 500))  # chặn page_size quá lớn gây nặng cụm ES
    from_offset = (page - 1) * page_size

    try:
        result = client.search(
            index=index_pattern,
            query=query,
            sort=[{sort_field: {"order": "desc"}}],
            from_=from_offset,
            size=page_size,
            track_total_hits=True,
        )
    except Exception as e:
        raise ValidationError(f"Không thể truy vấn cụm ELK ({cluster_name}): {str(e)}")

    total = result["hits"]["total"]["value"]
    return result["hits"]["hits"], total