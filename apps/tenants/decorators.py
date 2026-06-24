from functools import wraps

from django.http import JsonResponse

from apps.tenants.models import TenantUser


def tenant_admin_required(view_func):
    """✅ FIX: Decorator để kiểm tra tenant_admin permission"""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.role == TenantUser.ROLE_TENANT_ADMIN):
            return JsonResponse({'error': 'Permission denied'}, status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def superuser_required(view_func):
    """✅ FIX: Decorator để kiểm tra superuser permission"""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            return JsonResponse({'error': 'Permission denied'}, status=403)
        return view_func(request, *args, **kwargs)

    return wrapper