"""
WSGI config for ManagerSslLog project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os
from pathlib import Path

import environ
from django.core.wsgi import get_wsgi_application

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(env_file=str(BASE_DIR / '.env'))

# FIX: trước đây dùng os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ManagerSslLog.settings.local')
# -- nghĩa là nếu file .env thiếu dòng DJANGO_SETTINGS_MODULE (ví dụ quên
# điền khi deploy production), server vẫn khởi động được bình thường nhưng
# ÂM THẦM chạy bằng settings.local (DEBUG=True, ALLOWED_HOSTS=['*'], không
# có SECURE_PROXY_SSL_HEADER...). Lỗi này không hiện ra ngay, rất khó phát
# hiện cho tới khi có vấn đề bảo mật thật xảy ra.
#
# Giờ bắt buộc đọc đúng giá trị từ .env (qua env.str, không có default) --
# nếu thiếu, environ sẽ raise ImproperlyConfigured ngay khi khởi động, báo
# lỗi rõ ràng thay vì chạy nhầm môi trường.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', env.str('DJANGO_SETTINGS_MODULE'))

application = get_wsgi_application()