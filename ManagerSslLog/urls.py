from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.tenants.urls')),
    path('networks/', include('apps.core_networks.urls')),
    path('ssl/', include('apps.ssl_manager.urls')),
    path('monitor/', include('apps.monitor.urls')),
    path('soap/', include('apps.mailboxsoap.urls')),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
