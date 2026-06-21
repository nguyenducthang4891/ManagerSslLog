from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.exceptions import ValidationError


class SSLValidatorService:
    """Service chịu trách nhiệm parse dữ liệu và kiểm tra tính hợp lệ của bộ file SSL"""

    def __init__(self, server_cert_file, private_key_file):
        self.cert_bytes = server_cert_file.read()
        self.key_bytes = private_key_file.read()

        # Reset pointer của file về 0 để Django có thể lưu file vào ổ đĩa sau này
        server_cert_file.seek(0)
        private_key_file.seek(0)

    def validate_and_parse(self):
        try:
            # 1. Parse Server Certificate
            cert = x509.load_pem_x509_certificate(self.cert_bytes)
        except Exception:
            raise ValidationError("File Server Certificate không đúng định dạng PEM.")

        try:
            # 2. Parse Private Key
            private_key = serialization.load_pem_private_key(self.key_bytes, password=None)
        except Exception:
            raise ValidationError("File Private Key không đúng định dạng PEM hoặc có mật khẩu bảo vệ.")

        # 3. Kiểm tra cặp Key và Cert có khớp logic với nhau không (Match Modulus)
        if isinstance(private_key, rsa.RSAPrivateKey):
            cert_modulus = cert.public_key().public_numbers().n
            key_modulus = private_key.public_key().public_numbers().n
            if cert_modulus != key_modulus:
                raise ValidationError("Mã khóa học: Private Key không trùng khớp với Server Certificate!")

        # 4. Trích xuất thông tin chi tiết từ Cert
        subject = cert.subject
        issuer = cert.issuer

        try:
            common_name = subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        except IndexError:
            raise ValidationError("Không tìm thấy thông tin Common Name (CN) trong chứng chỉ.")

        try:
            issuer_name = issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        except IndexError:
            issuer_name = "Unknown Issuer"

        # Lấy các tên miền thay thế (SANs) nếu có
        sans = []
        try:
            ext = cert.extensions.get_extension_for_oid(x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
            sans = ext.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            pass

        return {
            "common_name": common_name,
            "issuer": issuer_name,
            "subject_alt_names": ", ".join(sans),
            "valid_from": cert.not_valid_before_utc,
            "valid_to": cert.not_valid_after_utc,
            "serial_number": str(cert.serial_number),
        }