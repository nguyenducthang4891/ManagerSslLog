from django.urls import re_path
from apps.monitor import consumers

websocket_urlpatterns = [
    re_path(r"ws/monitor/metrics/$", consumers.MonitorMetricConsumer.as_asgi()),
]