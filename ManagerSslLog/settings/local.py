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