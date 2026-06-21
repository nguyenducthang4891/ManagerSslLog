import os

from .base import *

# Bật debug môi trường dev
DEBUG = True

ALLOWED_HOSTS = ['*']

# Database SQLite cho môi trường local
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

# Tắt cấu hình bảo mật HTTPS rườm rà khi đang code ở local
SECURE_SSL_REDIRECT = False

REDIS_HOST = env("REDIS_HOST", default="localhost")
REDIS_PORT = env("REDIS_PORT", default="6379")
REDIS_PASSWORD = env("REDIS_PASSWORD", default="123456")
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

# =========================================================================
# CẤU HÌNH DJANGO CHANNELS LAYER (Dùng Redis)
# =========================================================================
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [f"redis://default:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/3"] ,
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

# =========================================================================
# CẤU HÌNH CELERY & CELERY BEAT
# =========================================================================
CELERY_BROKER_URL = 'redis://:123456@172.17.104.12:6379/4'
CELERY_RESULT_BACKEND = 'redis://:123456@172.17.104.12:6379/5'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# Vòng lặp định kỳ: Cứ 3 giây quét Elasticsearch 1 lần để đẩy Realtime
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'broadcast-monitor-metrics-every-3-seconds': {
        'task': 'apps.monitor.tasks.metric.broadcast_monitor_metrics',
        'schedule': 5.0, # Chạy định kỳ mỗi 3 giây
    },
}