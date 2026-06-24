# apps/ssl_manager/services/ssl_checker.py
import socket
import ssl
from datetime import datetime
from django.utils.timezone import make_aware


class SSLCheckService:
    @staticmethod
    def check_live_ssl(domain_name: str) -> dict:
        """Kết nối trực tiếp tới cổng 443 của domain để lấy thông tin SSL thực tế"""
        context = ssl.create_default_context()
        try:
            with socket.create_connection((domain_name, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=domain_name) as ssock:
                    cert = ssock.getpeercert()

                    # Parse ngày hết hạn từ chuỗi định dạng OpenSSL (VD: "Jan 24 23:59:59 2027 GMT")
                    not_after_str = cert.get('notAfter')
                    not_after = datetime.strptime(not_after_str, '%b %d %H:%M:%S %Y %Z')
                    not_after = make_aware(not_after)

                    # Lấy thông tin Issuer
                    issuer_dict = dict(x[0] for x in cert.get('issuer', ()))
                    issuer_name = issuer_dict.get('commonName', 'Unknown Issuer')

                    return {
                        'status': 'ok',
                        'issuer': issuer_name,
                        'valid_to': not_after.strftime('%Y-%m-%d %H:%M:%S'),
                        'is_expired': not_after < make_aware(datetime.utcnow())
                    }
        except Exception as e:
            return {
                'status': 'error',
                'message': f"Không thể kết nối hoặc xác thực SSL: {str(e)}"
            }