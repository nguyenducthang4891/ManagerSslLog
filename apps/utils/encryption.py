from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _get_fernet() -> Fernet:
    """
    Lấy Fernet key từ settings.FIELD_ENCRYPTION_KEY.
    Cần thêm vào settings.py:
        FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY")
    Sinh key một lần bằng: Fernet.generate_key().decode()
    """
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise RuntimeError(
            "Thiếu settings.FIELD_ENCRYPTION_KEY. Hãy sinh key bằng "
            "Fernet.generate_key() và khai báo trong settings/env."
        )
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


class EncryptedTextField(models.TextField):
    """
    TextField tự động mã hóa/giải mã giá trị bằng Fernet (AES-128-CBC + HMAC).
    Dữ liệu cũ (plaintext) vẫn đọc được nhờ fallback InvalidToken -> trả nguyên giá trị,
    để tránh crash khi migrate dữ liệu cũ chưa mã hóa (nên chạy script migrate dữ liệu sau khi deploy).
    """

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        f = _get_fernet()
        if isinstance(value, str):
            value = value.encode()
        return f.encrypt(value).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        f = _get_fernet()
        try:
            return f.decrypt(value.encode()).decode()
        except (InvalidToken, ValueError):
            # Dữ liệu cũ chưa mã hóa hoặc không decrypt được -> trả nguyên bản
            return value

    def to_python(self, value):
        return value