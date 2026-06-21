from django.core.exceptions import ValidationError
from apps.ssl_manager.models import SSLCertificate
from apps.core_networks.models import Domain
from .ssl_validator import SSLValidatorService


class SSLLifecycleService:

    @staticmethod
    def upload_and_create_certificate(user, domain_id: int, name: str,
                                      root_file, inter_file, server_file, key_file) -> SSLCertificate:
        """Upload bộ file SSL, tự động giải mã thông tin cấu trúc chuỗi chứng chỉ và lưu bản ghi"""
        try:
            if user.is_superuser:
                domain = Domain.objects.get(id=domain_id)
            else:
                domain = Domain.objects.get(id=domain_id, tenant=user.tenant)
        except Domain.DoesNotExist:
            raise ValidationError("Tên miền không hợp lệ hoặc không thuộc quyền quản lý của bạn.")

        validator = SSLValidatorService(server_cert_file=server_file, private_key_file=key_file)
        parsed_data = validator.validate_and_parse()

        clean_cn = parsed_data['common_name'].replace('*.', '')
        if clean_cn not in domain.name:
            raise ValidationError(
                f"Chứng chỉ cấp cho '{parsed_data['common_name']}' không khớp với tên miền đăng ký '{domain.name}'")

        cert = SSLCertificate(
            name=name,
            domain=domain,
            uploaded_by=user,
            root_cert=root_file,
            inter_cert=inter_file,
            server_cert=server_file,
            private_key=key_file,
            status=SSLCertificate.STATUS_VALID,
            common_name=parsed_data['common_name'],
            issuer=parsed_data['issuer'],
            subject_alt_names=parsed_data['subject_alt_names'],
            valid_from=parsed_data['valid_from'],
            valid_to=parsed_data['valid_to'],
            serial_number=parsed_data['serial_number']
        )
        cert.save()
        return cert

    # FIX: method trigger_deploy_process() đã bị loại bỏ khỏi đây.
    #
    # Lý do: trước đây view gọi method này TRONG MỘT THREAD RIÊNG. Mọi
    # ValidationError (vd. "không tìm thấy cert", "trạng thái không hợp lệ")
    # raise bên trong thread sẽ không bao giờ tới được response HTTP, vì
    # response đã được trả về ngay sau khi gọi thread.start(). Hậu quả:
    # - User không có quyền với cert đó vẫn nhận "deploy đã kích hoạt thành công"
    # - Cert ở trạng thái invalid/deploying vẫn nhận "deploy đã kích hoạt thành công"
    # - Lỗi thực sự chỉ nằm im trong log server, không ai biết để xử lý.
    #
    # Validate quyền + trạng thái giờ được thực hiện ĐỒNG BỘ tại
    # apps.ssl_manager.views.api_trigger_deploy (qua SSLLifecycleService.get_detail),
    # và chỉ phần thao tác SSH thực sự dài hơi (ZimbraDeployService.execute_deploy)
    # mới chạy trong thread riêng.

    @staticmethod
    def delete_certificate(user, cert_id: int):
        """Xóa hồ sơ lưu trữ chứng chỉ khỏi hệ thống"""
        try:
            if user.is_superuser:
                cert = SSLCertificate.objects.get(id=cert_id)
            else:
                cert = SSLCertificate.objects.get(id=cert_id, domain__tenant=user.tenant)
        except SSLCertificate.DoesNotExist:
            raise ValidationError("Không tìm thấy chứng chỉ cần xóa.")

        if cert.status == SSLCertificate.STATUS_DEPLOYING:
            raise ValidationError("Hệ thống đang tiến hành deploy, không được phép xóa bản ghi.")

        cert.delete()

    @staticmethod
    def get_list(user, status_filter: str = None) -> list[SSLCertificate]:
        """Lấy danh sách lịch sử lưu trữ chứng chỉ SSL có lọc phân quyền theo Tenant"""
        if user.is_superuser:
            queryset = SSLCertificate.objects.all()
        elif user.tenant:
            queryset = SSLCertificate.objects.filter(domain__tenant=user.tenant)
        else:
            return SSLCertificate.objects.none()

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        return queryset.select_related('domain', 'uploaded_by').order_by('-created_at')

    @staticmethod
    def get_detail(user, cert_id: int) -> SSLCertificate:
        """Xem chi tiết chứng chỉ (Trả về kèm deploy_log để Polling Log Real-time trên giao diện)"""
        try:
            if user.is_superuser:
                return SSLCertificate.objects.select_related('domain__server').get(id=cert_id)
            return SSLCertificate.objects.select_related('domain__server').get(id=cert_id, domain__tenant=user.tenant)
        except SSLCertificate.DoesNotExist:
            raise ValidationError("Chứng chỉ không tồn tại hoặc bạn không có quyền truy cập.")