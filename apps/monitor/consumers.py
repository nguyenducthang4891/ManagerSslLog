import json
from channels.generic.websocket import AsyncWebsocketConsumer

from channels.db import database_sync_to_async


class MonitorMetricConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = "group_monitor_metrics"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # Hàm này lắng nghe tin nhắn từ Celery Beat gửi vào Group qua Channel Layer
    async def send_metrics(self, event):
        # Lấy dữ liệu metric ra
        data = event["data"]
        # Đẩy trực tiếp xuống trình duyệt (Không lo bị block luồng)
        await self.send(text_data=json.dumps(data))