from django.urls import path
from apps.core_networks import views

urlpatterns = [
    # Template Views
    path('servers/', views.server_list_view, name='server_list'),
    path('domains/', views.domain_list_view, name='domain_list'),

    # API Endpoints
    path('api/servers/add/', views.api_add_server, name='api_add_server'),
    path('api/servers/<int:server_id>/edit/', views.api_edit_server, name='api_edit_server'),

    path('api/domains/add/', views.api_add_domain, name='api_add_domain'),
    # FIX: route này bị thiếu trong bản gốc -> template gọi /edit/ luôn ra 404.
    path('api/domains/<int:domain_id>/edit/', views.api_edit_domain, name='api_edit_domain'),
    path('api/domains/<int:domain_id>/delete/', views.api_delete_domain, name='api_delete_domain'),
    path('api/domains/<int:domain_id>/status/', views.api_change_domain_status, name='api_change_domain_status'),

    path('api/domains/assign-tenant/', views.api_assign_domain_tenant, name='api_assign_domain_tenant'),

    path('api/servers/<int:server_id>/test-connection/', views.api_test_server_connection,
         name='api_test_server_connection'),
    path('api/servers/<int:server_id>/test-soap/', views.api_test_soap_connection, name='api_test_soap_connection'),
]