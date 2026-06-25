"""
apps/mailbox/views.py

View FBV cho chức năng Tìm kiếm & Quản lý Email (theo pattern của apps.core_networks
và apps.tenants: login_required + service layer xử lý nghiệp vụ/phân quyền, view
chỉ parse request & trả JsonResponse).
"""
from django.shortcuts import render
from django.http import JsonResponse, StreamingHttpResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
import httpx

from apps.mailboxsoap.services import MailboxService, MailboxPermissionService, PROFILE_ATTRS


@login_required(login_url='login')
def mailbox_search_view(request):
    """Trang Tìm kiếm Email: hiển thị select domain (theo quyền) + ô tìm kiếm."""
    domains = MailboxPermissionService.get_allowed_domains(request.user)
    can_manage = MailboxPermissionService.can_manage_account(request.user)

    context = {
        'domains': domains,
        'can_manage': can_manage,  # False => template chỉ render nút Reset Password
    }
    return render(request, 'mailboxsoap/mailbox_search.html', context)


@login_required(login_url='login')
def api_mailbox_search(request):
    """GET ?domain_id=&q=&offset= -> list account khớp email trong domain (infinite scroll)."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.GET.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Vui lòng chọn tên miền cần tìm kiếm.'}, status=400)

    query = request.GET.get('q', '')

    try:
        offset = int(request.GET.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0

    try:
        search_result = MailboxService.search(request.user, domain_id, query, offset=offset)
        return JsonResponse(search_result)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi truy vấn Zimbra: {str(e)}'}, status=502)


@login_required(login_url='login')
def api_mailbox_detail(request):
    """GET ?domain_id=&email= -> chi tiết 1 account (dùng khi mở modal sửa)."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.GET.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Tên miền không hợp lệ.'}, status=400)

    email = request.GET.get('email', '')

    try:
        detail = MailboxService.get_detail(request.user, domain_id, email)
        return JsonResponse({'detail': detail})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi truy vấn Zimbra: {str(e)}'}, status=502)


@login_required(login_url='login')
def api_mailbox_update_profile(request):
    """POST: sửa givenName/sn/displayName/title/mobile. Superuser & Tenant Admin."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.POST.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Tên miền không hợp lệ.'}, status=400)

    email = request.POST.get('email', '')
    profile = {field: request.POST.get(field, '') for field in PROFILE_ATTRS}

    try:
        MailboxService.update_profile(request.user, domain_id, email, profile)
        return JsonResponse({'message': f'Đã cập nhật thông tin hồ sơ cho {email}.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi cập nhật trên Zimbra: {str(e)}'}, status=502)


@login_required(login_url='login')
def api_mailbox_reset_password(request):
    """
    POST: reset password.
    DUY NHẤT action mailbox mà Nhân viên (tenant_user) cũng được phép gọi --
    service layer chỉ kiểm tra domain có thuộc tenant của họ hay không.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.POST.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Tên miền không hợp lệ.'}, status=400)

    email = request.POST.get('email', '')
    new_password = request.POST.get('new_password', '')

    try:
        MailboxService.reset_password(request.user, domain_id, email, new_password)
        return JsonResponse({'message': f'Đã đặt lại mật khẩu cho {email}.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi đặt lại mật khẩu trên Zimbra: {str(e)}'}, status=502)


@login_required(login_url='login')
def api_mailbox_rename(request):
    """POST: đổi tên (đổi địa chỉ) email. Superuser & Tenant Admin."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.POST.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Tên miền không hợp lệ.'}, status=400)

    email = request.POST.get('email', '')
    new_email = request.POST.get('new_email', '')

    try:
        MailboxService.rename(request.user, domain_id, email, new_email)
        return JsonResponse({'message': f'Đã đổi tên email {email} thành {new_email}.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi đổi tên email trên Zimbra: {str(e)}'}, status=502)


@login_required(login_url='login')
def api_mailbox_set_status(request):
    """POST: đổi trạng thái active/locked/closed. Superuser & Tenant Admin."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.POST.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Tên miền không hợp lệ.'}, status=400)

    email = request.POST.get('email', '')
    status = request.POST.get('status', '')

    try:
        MailboxService.set_status(request.user, domain_id, email, status)
        label = {'active': 'Hoạt động', 'locked': 'Khóa', 'closed': 'Đóng'}.get(status, status)
        return JsonResponse({'message': f'Đã chuyển trạng thái {email} thành "{label}".'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi đổi trạng thái trên Zimbra: {str(e)}'}, status=502)


@login_required(login_url='login')
def api_mailbox_delete(request):
    """POST: xóa vĩnh viễn account. Superuser & Tenant Admin."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.POST.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Tên miền không hợp lệ.'}, status=400)

    email = request.POST.get('email', '')

    try:
        MailboxService.delete(request.user, domain_id, email)
        return JsonResponse({'message': f'Đã xóa vĩnh viễn tài khoản email {email}.'})
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Lỗi xóa email trên Zimbra: {str(e)}'}, status=502)


@login_required(login_url='login')
def mailbox_backup_download(request):
    """
    GET: tải file backup .tgz của 1 mailbox.
    Stream trực tiếp từ Zimbra (https://<host>:7071/home/<email>/?fmt=tgz, HTTP
    Basic Auth bằng admin email/password của ZimbraServer) về client, KHÔNG ghi
    file tạm ra disk server Django và không load toàn bộ file vào RAM.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        domain_id = int(request.GET.get('domain_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Tên miền không hợp lệ.'}, status=400)

    email = request.GET.get('email', '')

    try:
        server, email = MailboxService.get_backup_target(request.user, domain_id, email)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)

    backup_url = f"https://{server.hostname}:7071/home/{email}/?fmt=tgz"

    try:
        client = httpx.Client(
            verify=False, timeout=120.0,
            auth=(server.zimbra_admin_email, server.zimbra_admin_password),
        )
        upstream = client.send(client.build_request("GET", backup_url), stream=True)
    except httpx.RequestError as exc:
        return JsonResponse({'error': f'Không thể kết nối tới Zimbra Server để tải backup: {exc}'}, status=502)

    if upstream.status_code != 200:
        upstream.close()
        client.close()
        return JsonResponse(
            {'error': f'Zimbra từ chối yêu cầu tải backup (HTTP {upstream.status_code}). '
                      f'Kiểm tra lại quyền Admin hoặc email có tồn tại không.'},
            status=502,
        )

    def stream_and_cleanup():
        try:
            for chunk in upstream.iter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            upstream.close()
            client.close()

    safe_filename = email.replace('@', '_at_')
    response = StreamingHttpResponse(stream_and_cleanup(), content_type='application/x-gzip')
    response['Content-Disposition'] = f'attachment; filename="{safe_filename}_backup.tgz"'
    return response