from django.urls import path
from apps.tenants import views

urlpatterns = [
    # Template Views
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_action, name='logout'),
    path('api/users/me/change-password/', views.api_change_password, name='api_change_password'),
    path('', views.dashboard_view, name='dashboard'),
    path('users/', views.user_list_view, name='user_list'),

    # API Endpoints
    path('api/users/create/', views.api_create_staff, name='api_create_staff'),
    path('api/users/<int:user_id>/status/', views.api_change_user_status, name='api_change_user_status'),
    # MỚI: cho phép Tenant Admin tự đổi vai trò nhân viên trong tổ chức mình.
    path('api/users/<int:user_id>/role/', views.api_change_user_role, name='api_change_user_role'),
path('api/users/<int:user_id>/reset-password/', views.api_reset_user_password, name='api_reset_user_password'),


    path('tenants/', views.tenant_list, name='tenant_list'),
    path('api/tenants/add/', views.api_add_tenant, name='api_add_tenant'),
    path('api/tenants/<int:tenant_id>/edit/', views.api_edit_tenant, name='api_edit_tenant'),
    path('api/tenants/<int:tenant_id>/delete/', views.api_delete_tenant, name='api_delete_tenant'),
    path('api/tenants/assign-admin/', views.api_assign_tenant_admin, name='api_assign_tenant_admin'),
]