python manage.py migrate --settings=ManagerSslLog.settings.local


$env:DJANGO_SETTINGS_MODULE="ManagerSslLog.settings.local"
daphne -b 0.0.0.0 -p 8000 PortalEmailGov.asgi:application
celery -A ManagerSslLog worker --loglevel=info --pool solo