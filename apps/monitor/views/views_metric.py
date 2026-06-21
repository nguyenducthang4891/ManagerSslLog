from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError

from apps.monitor.services import MetricService


@login_required(login_url='login')
def metric(request):
    """Trang tổng quan giám sát: tổng số cảnh báo warning/critical 24h gần nhất."""
    try:
        summary = MetricService.get_alert_summary(request.user, hours=24)
    except ValidationError:
        summary = {"total_samples": 0, "warning_count": 0, "critical_count": 0, "elk_cluster": None}

    return render(request, 'monitor/metric.html', {'summary': summary})


@login_required(login_url='login')
def api_query_metric(request):
    """
    API Query luồng Metric từ Elasticsearch:
    - hours / days: Số khoảng khoảng thời gian lùi về trước.
    - severity: Lọc mức độ cảnh báo.
    - hostname: Tên máy chủ cụ thể cần lấy log.
    """
    # Ép kiểu dữ liệu trống từ Client về dạng Chuỗi rỗng an toàn trước khi xử lý
    hours_raw = request.GET.get('hours', '').strip()
    days_raw = request.GET.get('days', '').strip()

    severity = request.GET.get('severity') or None
    hostname = request.GET.get('hostname') or None

    try:
        # CHẶN LỖI 400: Chỉ ép kiểu int khi chuỗi thực sự có ký tự số, chuỗi rỗng trả về None
        hours = int(hours_raw) if hours_raw else None
        days = int(days_raw) if days_raw else None

        # Trường hợp cả 2 tham số trống (do tự động reload hoặc khởi tạo lỗi), đặt mặc định 24h
        if hours is None and days is None:
            hours = 24
    except ValueError:
        return JsonResponse({'error': 'Tham số truy vấn thời gian lùi (hours/days) phải ở định dạng số.'}, status=400)

    if severity and severity not in ('warning', 'critical', 'ok'):
        return JsonResponse({'error': 'Tham số phân loại mức độ cảnh báo không hợp lệ.'}, status=400)

    try:
        data = MetricService.query(
            request.user, hours=hours, days=days,
            severity_filter=severity, hostname=hostname,
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def api_alert_summary(request):
    hours_raw = request.GET.get('hours', '24').strip()
    try:
        hours = int(hours_raw) if hours_raw else 24
    except ValueError:
        return JsonResponse({'error': 'Tham số hours không hợp lệ.'}, status=400)

    try:
        summary = MetricService.get_alert_summary(request.user, hours=hours)
        return JsonResponse(summary)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)


@login_required(login_url='login')
def host_detail_view(request, hostname):
    """Trả về giao diện xem chi tiết chuỗi lịch sử log của duy nhất một host cụ thể"""
    return render(request, 'monitor/metric_detail.html', {'hostname': hostname})


@login_required(login_url='login')
def api_host_logs(request):
    """API phục vụ trang detail, hiển thị Timeseries Log của 1 host máy chủ duy nhất"""
    hostname = request.GET.get('hostname')
    hours_raw = request.GET.get('hours', '24').strip()
    severity = request.GET.get('severity') or None

    if not hostname:
        return JsonResponse({'error': 'Thiếu tham số cấu hình hostname đích cần tra cứu.'}, status=400)

    try:
        hours = int(hours_raw) if hours_raw else 24
    except ValueError:
        return JsonResponse({'error': 'Định dạng số giờ lịch sử không đúng cấu trúc.'}, status=400)

    try:
        data = MetricService.query(
            request.user, hours=hours, days=None,
            severity_filter=severity, hostname=hostname,
            page_size=300
        )
        return JsonResponse(data)
    except ValidationError as e:
        return JsonResponse({'error': str(e.message)}, status=400)