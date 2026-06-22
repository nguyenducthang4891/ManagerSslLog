import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


def _group_name_for_tenant(tenant_id) -> str:
    """
    Tên group Channel Layer ứng với 1 tenant cụ thể. Không có group "toàn cục"
    -- mỗi tenant luôn có group riêng để đảm bảo cô lập dữ liệu khi broadcast.
    """
    return f"group_monitor_metrics_tenant_{tenant_id}"


class MonitorMetricConsumer(AsyncWebsocketConsumer):
    """
    BẢO MẬT: Trước đây connect() tự add mọi client (kể cả chưa đăng nhập)
    vào 1 group DUY NHẤT "group_monitor_metrics" -- nghĩa là dữ liệu của
    MỌI tenant bị phát cho MỌI client đang mở WebSocket, không phân biệt
    quyền truy cập. Đây là lỗi rò rỉ dữ liệu cross-tenant nghiêm trọng.

    Cách sửa:
    - connect(): CHỈ accept() sau khi xác nhận user đã đăng nhập. Không tự
      join group nào cả -- client phải gửi message "subscribe" kèm tenant_id
      muốn xem.
    - Khi nhận "subscribe": xác định tenant THỰC SỰ được phép xem (ép theo
      user.tenant nếu không phải superuser, validate quyền nếu là superuser
      chọn 1 tenant cụ thể). Superuser KHÔNG ĐƯỢC subscribe "tất cả tenant"
      cùng lúc -- phải chọn đúng 1 tenant mỗi lần, đúng yêu cầu nghiệp vụ
      (superuser chỉ xem được khi đã chọn tenant qua select2 trên UI).
    - Mỗi tenant có group riêng (group_monitor_metrics_tenant_<id>) nên
      broadcast của tenant A không bao giờ tới được client của tenant B.
    """

    async def connect(self):
        user = self.scope.get("user")

        if user is None or not user.is_authenticated:
            # Từ chối thẳng -- không accept(), không add group.
            await self.close(code=4001)
            return

        self.current_group = None
        self.user = user
        await self.accept()

    async def disconnect(self, close_code):
        if getattr(self, "current_group", None):
            await self.channel_layer.group_discard(self.current_group, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """
        Giao thức đơn giản từ client:
            {"action": "subscribe", "tenant_id": <int|null>}
        Server tự quyết định group THỰC SỰ join dựa theo quyền của user,
        KHÔNG tin tưởng tenant_id client gửi lên một cách tuyệt đối.
        """
        try:
            payload = json.loads(text_data or "{}")
        except (TypeError, ValueError):
            await self.send(text_data=json.dumps({"error": "Payload không hợp lệ."}))
            return

        if payload.get("action") != "subscribe":
            return

        requested_tenant_id = payload.get("tenant_id")
        resolved_tenant_id = await self._resolve_allowed_tenant_id(requested_tenant_id)

        if resolved_tenant_id is None:
            # Superuser chưa chọn tenant nào (hoặc chọn tenant không hợp lệ)
            # -- không join group nào, không nhận data, đúng yêu cầu nghiệp vụ.
            await self._leave_current_group()
            await self.send(text_data=json.dumps({
                "subscribed": False,
                "message": "Vui lòng chọn tổ chức (tenant) để xem dữ liệu giám sát.",
            }))
            return

        await self._leave_current_group()
        self.current_group = _group_name_for_tenant(resolved_tenant_id)
        await self.channel_layer.group_add(self.current_group, self.channel_name)
        await self.send(text_data=json.dumps({"subscribed": True, "tenant_id": resolved_tenant_id}))

    async def _leave_current_group(self):
        if getattr(self, "current_group", None):
            await self.channel_layer.group_discard(self.current_group, self.channel_name)
            self.current_group = None

    @database_sync_to_async
    def _resolve_allowed_tenant_id(self, requested_tenant_id):
        """
        - Non-superuser: LUÔN ép về user.tenant_id của chính họ, bỏ qua hoàn
          toàn tenant_id client gửi lên (chống user tự sửa request để xem
          tenant khác). Nếu user không thuộc tenant nào -> None (không xem gì).
        - Superuser: chỉ được join group của đúng 1 tenant đang tồn tại mà
          họ chỉ định qua select2. Không truyền/None -> không join group nào.
        """
        user = self.user

        if not user.is_superuser:
            return user.tenant_id  # có thể là None nếu user không thuộc tenant nào

        if not requested_tenant_id:
            return None

        from apps.tenants.models import Tenant
        if Tenant.objects.filter(id=requested_tenant_id).exists():
            return requested_tenant_id
        return None

    # Hàm này lắng nghe tin nhắn từ Celery Beat gửi vào Group qua Channel Layer
    async def send_metrics(self, event):
        data = event["data"]
        await self.send(text_data=json.dumps(data))