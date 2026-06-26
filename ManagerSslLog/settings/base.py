import os
from pathlib import Path

import environ

# 1. Xác định đường dẫn thư mục gốc dự án (D:\Programming\ManagerSslLog)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 2. Load file .env
env = environ.Env()
environ.Env.read_env(env_file=str(BASE_DIR / '.env'))
# Cấu hình bảo mật cơ bản
SECRET_KEY = 'django-insecure-rz+sal&v_jj$v0k#ccz-0!109@%)q26@+94f3er&^q&%+hf%ef'
FIELD_ENCRYPTION_KEY = os.environ.get(
    "FIELD_ENCRYPTION_KEY",
    "q_MAlRlQHV01tpaye-eFOxh_WbHUPqVaTna3fkIyFBY="  # CHỈ dùng tạm cho dev, đổi key thật cho production
)
# Định nghĩa các App hệ thống và App nội bộ
INSTALLED_APPS = [
    'daphne',
    'channels',
    'django.contrib.admin',  # Thêm admin vào nếu bạn cần dùng giao diện admin mặc định
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    # Các module core nằm trong apps/
    'apps.tenants',
    'apps.core_networks',
    'apps.ssl_manager',
    'apps.monitor',
    'apps.mailboxsoap'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

WHITENOISE_USE_FINDERS = True
import mimetypes

mimetypes.add_type("application/javascript", ".js", True)
mimetypes.add_type("text/css", ".css", True)

ROOT_URLCONF = 'ManagerSslLog.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'ManagerSslLog.wsgi.application'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Cấu hình ngôn ngữ & múi giờ Việt Nam phù hợp cho hệ thống log
LANGUAGE_CODE = 'vi-vn'
TIME_ZONE = 'Asia/Ho_Chi_Minh'
USE_I18N = True
USE_TZ = True

# Cấu hình tĩnh (Static)

STATIC_ROOT = BASE_DIR / 'static_root'
STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR / 'static'
]
# Cấu hình lưu trữ File (Nơi chứa file certificates)
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'storage' / 'media'

# BẮT BUỘC: Trỏ cấu hình User sang Login bằng Email của app tenants
AUTH_USER_MODEL = 'tenants.TenantUser'

# 2. Đưa class vừa tạo vào danh sách cấu hình của Django
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8}
    },
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
    {
        'NAME': 'apps.tenants.validators.ComplexPasswordValidator',
    },
]
