import json
from channels.generic.websocket import AsyncWebsocketConsumer


class MonitorMetricConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.group_name = "monitor_metrics_group"

        # Kiểm tra quyền đăng nhập qua Session mã nguồn Django
        if self.scope["user"].is_authenticated:
            # Tham gia vào nhóm nhận tin
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Hàm xử lý khi có tín hiệu gửi từ Celery Worker / Script quét dữ liệu
    async def send_metrics_update(self, event):
        # Đẩy trực tiếp JSON thô xuống trình duyệt Client
        await self.send(text_data=json.dumps(event["data"]))