import os
from .base import *

# TẮT TUYỆT ĐỐI debug trên production
DEBUG = False

# Điền domain hoặc IP chạy server production thực tế của bạn vào đây
ALLOWED_HOSTS = ['yourdomain.com', '192.168.1.x']

# Database PostgreSQL chuẩn Production (Lấy thông tin từ Environment Variables để bảo mật)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'manager_ssl_db'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'your_secure_password'),
        'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# Cấu hình bảo mật bắt buộc trên Production
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True # Ép buộc chuyển hướng HTTP sang HTTPS
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = 'DENY'