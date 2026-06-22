import os
from pathlib import Path

from django.core.asgi import get_asgi_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
import environ

# 1. Xác định đường dẫn thư mục gốc dự án (D:\Programming\ManagerSslLog)
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. Load file .env
env = environ.Env()
environ.Env.read_env(env_file=str(BASE_DIR / '.env'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', env.str('DJANGO_SETTINGS_MODULE'))
# Khởi tạo ứng dụng ASGI và bọc static
django_asgi_app = ASGIStaticFilesHandler(get_asgi_application())

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator # 🌟 Thêm bộ kiểm tra bảo mật Host chống nghẽn
import apps.monitor.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(  # 🌟 Bọc thêm lớp bảo vệ chống nghẽn gói handshake
        AuthMiddlewareStack(
            URLRouter(apps.monitor.routing.websocket_urlpatterns)
        )
    ),
})