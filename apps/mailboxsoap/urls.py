from django.urls import path
from apps.mailboxsoap import views

urlpatterns = [
    # Template View
    path('mailbox/', views.mailbox_search_view, name='mailbox_search'),

    # API Endpoints
    path('api/mailbox/search/', views.api_mailbox_search, name='api_mailbox_search'),
    path('api/mailbox/detail/', views.api_mailbox_detail, name='api_mailbox_detail'),
    path('api/mailbox/update-profile/', views.api_mailbox_update_profile, name='api_mailbox_update_profile'),
    path('api/mailbox/reset-password/', views.api_mailbox_reset_password, name='api_mailbox_reset_password'),
    path('api/mailbox/rename/', views.api_mailbox_rename, name='api_mailbox_rename'),
    path('api/mailbox/set-status/', views.api_mailbox_set_status, name='api_mailbox_set_status'),
    path('api/mailbox/delete/', views.api_mailbox_delete, name='api_mailbox_delete'),
    path('api/mailbox/backup/', views.mailbox_backup_download, name='mailbox_backup_download'),
]
