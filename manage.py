#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path
import environ # 🌟 Thêm import này vào đầu file

def main():
    # 1. Xác định thư mục gốc chứa file .env
    BASE_DIR = Path(__file__).resolve().parent
    
    # 2. Khởi tạo và nạp file .env ngay tại đây
    env = environ.Env()
    environ.Env.read_env(env_file=str(BASE_DIR / '.env'))
    
    # 3. Lấy biến settings, nếu không có trong .env thì mặc định chạy bản local hoặc production
    # (Ở đây tôi để mặc định là ManagerSslLog.settings.base nếu .env trống)
    django_settings = env.str('DJANGO_SETTINGS_MODULE', 'ManagerSslLog.settings.base')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', django_settings)

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)

if __name__ == '__main__':
    main()