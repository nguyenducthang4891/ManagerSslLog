import os
import environ
from pathlib import Path
from celery import Celery

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(env_file=str(BASE_DIR / '.env'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', env.str('DJANGO_SETTINGS_MODULE'))
app = Celery('ManagerSslLog')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()