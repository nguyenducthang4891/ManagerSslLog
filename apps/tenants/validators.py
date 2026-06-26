from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError

class ComplexPasswordValidator:
    def __init__(self):
        # Kiểm tra đồng thời: ít nhất 1 chữ thường, 1 chữ hoa, 1 số, 1 ký tự đặc biệt
        self.regex_validator = RegexValidator(
            regex=r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&._\-#^&+=\[\]{}()]).+$',
            message="Mật khẩu phải chứa ít nhất 1 chữ cái viết hoa, 1 chữ cái viết thường, 1 chữ số và 1 ký tự đặc biệt."
        )

    def validate(self, password, user=None):
        try:
            self.regex_validator(password)
        except ValidationError as e:
            raise ValidationError(e.message, code='password_too_weak')

    def get_help_text(self):
        return "Mật khẩu phải bao gồm cả chữ hoa, chữ thường, số và ký tự đặc biệt."