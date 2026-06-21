import os

from .base import *

# ============================================================================
# settings/production.py
# ----------------------------------------------------------------------------
# Dùng khi deploy thật, đứng SAU Nginx làm reverse proxy + SSL termination:
#   Browser --HTTPS/WSS--> Nginx (console.cantho.gov.vn:443)
#                              --HTTP/WS thuần--> Daphne (127.0.0.1:8000)
#
# Khác biệt cốt lõi so với local.py (dev): Daphne ở đây KHÔNG tự phục vụ
# HTTPS -- nó chỉ nhận HTTP/WS thuần nội bộ từ Nginx. Nếu không khai báo
# SECURE_PROXY_SSL_HEADER, Django sẽ tưởng MỌI request là HTTP không an
# toàn (vì về mặt kỹ thuật, kết nối giữa Nginx và Daphne đúng là HTTP),
# dẫn tới: cookie session/csrf không được đánh dấu Secure đúng cách,
# request.is_secure() luôn trả về False, và mọi logic dựa vào is_secure()
# (nếu có) sẽ chạy sai.
# ============================================================================

DEBUG = False

ALLOWED_HOSTS = ['console.cantho.gov.vn','monitor.vnptemail.vn','console.vnptemail.vn']

# CSRF_TRUSTED_ORIGINS bắt buộc từ Django 4+ khi frontend gọi POST qua HTTPS
# tới domain khác scheme mặc định -- phải khai đầy đủ scheme.
CSRF_TRUSTED_ORIGINS = ['https://console.cantho.gov.vn','https://monitor.vnptemail.vn','https://console.vnptemail.vn']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'manager_ssl_db'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

# ----------------------------------------------------------------------------
# QUAN TRỌNG NHẤT: báo cho Django biết request gốc là HTTPS dựa vào header
# Nginx gắn vào. Header tên là gì PHẢI khớp 100% với dòng
# "proxy_set_header X-Forwarded-Proto $scheme;" trong nginx.conf -- xem file
# nginx/console.cantho.gov.vn.conf đi kèm. Nếu thiếu dòng này ở Nginx, hoặc
# tên header không khớp, Django vẫn coi mọi request là HTTP, các cờ Secure
# dưới đây sẽ khiến CSRF/session cookie không bao giờ được set -> người
# dùng bị đăng xuất liên tục hoặc lỗi 403 CSRF khó hiểu.
# ----------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Daphne phía sau Nginx không tự redirect HTTP->HTTPS -- để Nginx làm việc đó
# (xem nginx conf: listen 80 redirect sang 443). Bật SECURE_SSL_REDIRECT=True
# ở Django tầng này có thể gây redirect loop vì Django thấy "đã là https"
# (nhờ SECURE_PROXY_SSL_HEADER ở trên) nên không cần tự redirect thêm.
SECURE_SSL_REDIRECT = False

# Cookie chỉ gửi qua kết nối HTTPS -- AN TOÀN để bật vì giờ Django đã biết
# đúng request là HTTPS (nhờ SECURE_PROXY_SSL_HEADER).
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS: báo browser luôn dùng HTTPS cho domain này trong 1 năm. Chỉ bật sau
# khi đã chắc chắn SSL hoạt động ổn định -- bật nhầm lúc SSL chưa xong sẽ
# khiến browser từ chối kết nối HTTP trong tối đa 1 năm tới (cache rất lâu).
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# ----------------------------------------------------------------------------
# Redis/Celery/Channels: giữ nguyên cấu hình như local.py, chỉnh lại theo
# host Redis thật của production qua biến môi trường (KHÔNG hard-code IP nội
# bộ vào source code production để dễ đổi hạ tầng sau này mà không sửa code).
# ----------------------------------------------------------------------------
REDIS_HOST = env("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = env("REDIS_PORT", default="6379")
REDIS_PASSWORD = env("REDIS_PASSWORD")
REDIS_DBCACHE = env("REDIS_DBCACHE", default=1)
REDIS_DBSESSION = env("REDIS_DBSESSION", default=2)

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://default:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DBCACHE}",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    },
    "sessions": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://default:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DBSESSION}",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    },
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [f"redis://default:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/7"],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

CELERY_BROKER_URL = 'redis://:123456@localhost:6379/8'
CELERY_RESULT_BACKEND = 'redis://:123456@localhost:6379/9'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

CELERY_BEAT_SCHEDULE = {
    'broadcast-monitor-metrics-every-3-seconds': {
        'task': 'apps.monitor.tasks.metric.broadcast_monitor_metrics',
        'schedule': 5.0,
    },
}