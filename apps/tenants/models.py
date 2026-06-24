from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone


class Tenant(models.Model):
    name = models.CharField(max_length=255, verbose_name="Tên Tổ chức")
    code = models.SlugField(max_length=100, unique=True, verbose_name="Mã định danh (Slug)")
    is_active = models.BooleanField(default=True, verbose_name="Trạng thái hoạt động")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"

    def __str__(self):
        return self.name


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Bắt buộc phải có địa chỉ Email")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class TenantUser(AbstractBaseUser, PermissionsMixin):
    ROLE_TENANT_ADMIN = "tenant_admin"
    ROLE_TENANT_USER = "tenant_user"
    ROLE_CHOICES = [
        (ROLE_TENANT_ADMIN, "Quản trị tổ chức "),
        (ROLE_TENANT_USER, "Nhân viên"),
    ]

    email = models.EmailField(unique=True, verbose_name="Địa chỉ Email")
    full_name = models.CharField(max_length=150, blank=True, verbose_name="Họ và tên")

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True,db_index=True,
        related_name="users", verbose_name="Thuộc Tenant"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_TENANT_USER, verbose_name="Quyền hạn")

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Thành viên tổ chức"
        verbose_name_plural = "Thành viên tổ chức"

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"