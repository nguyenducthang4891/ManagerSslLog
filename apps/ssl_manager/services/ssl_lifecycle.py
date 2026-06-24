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
    def update_certificate(user, cert_id: int, name: str, domain_id: int,
                           root_file=None, inter_file=None, server_file=None, key_file=None) -> SSLCertificate:
        """Cập nhật thông tin/file của SSL nếu chưa từng deploy thành công hoặc đang deploy"""
        try:
            if user.is_superuser:
                cert = SSLCertificate.objects.get(id=cert_id)
            else:
                cert = SSLCertificate.objects.get(id=cert_id, domain__tenant=user.tenant)
        except SSLCertificate.DoesNotExist:
            raise ValidationError("Không tìm thấy chứng chỉ hoặc bạn không có quyền chỉnh sửa.")

        # Chỉ cho phép sửa nếu chưa deploy thành công hoặc đang deploy
        ALLOW_UPDATE_STATUSES = [
            SSLCertificate.STATUS_PENDING,
            SSLCertificate.STATUS_VALID,
            SSLCertificate.STATUS_INVALID,
            SSLCertificate.STATUS_FAILED
        ]
        if cert.status not in ALLOW_UPDATE_STATUSES:
            raise ValidationError("Chứng chỉ đã deploy hoặc đang trong tiến trình deploy, không được phép chỉnh sửa.")

        try:
            if user.is_superuser:
                domain = Domain.objects.get(id=domain_id)
            else:
                domain = Domain.objects.get(id=domain_id, tenant=user.tenant)
        except Domain.DoesNotExist:
            raise ValidationError("Tên miền không hợp lệ hoặc không thuộc quyền quản lý của bạn.")

        cert.name = name
        cert.domain = domain

        # Nếu có upload file mới thì cập nhật và re-validate
        if server_file or key_file:
            # Sử dụng file mới nếu có, nếu không thì dùng lại file cũ dạng FieldFile
            s_file = server_file if server_file else cert.server_cert
            k_file = key_file if key_file else cert.private_key

            validator = SSLValidatorService(server_cert_file=s_file, private_key_file=k_file)
            parsed_data = validator.validate_and_parse()

            clean_cn = parsed_data['common_name'].replace('*.', '')
            if clean_cn not in domain.name:
                raise ValidationError(
                    f"Chứng chỉ cấp cho '{parsed_data['common_name']}' không khớp với tên miền đăng ký '{domain.name}'")

            cert.common_name = parsed_data['common_name']
            cert.issuer = parsed_data['issuer']
            cert.subject_alt_names = parsed_data['subject_alt_names']
            cert.valid_from = parsed_data['valid_from']
            cert.valid_to = parsed_data['valid_to']
            cert.serial_number = parsed_data['serial_number']
            cert.status = SSLCertificate.STATUS_VALID

        if root_file:
            cert.root_cert = root_file
        if inter_file:
            cert.inter_cert = inter_file
        if server_file:
            cert.server_cert = server_file
        if key_file:
            cert.private_key = key_file

        cert.save()
        return cert

    @staticmethod
    def delete_certificate(user, cert_id: int):
        """Xóa hồ sơ lưu trữ chứng chỉ (Chỉ cho phép nếu chưa deploy, hết hạn hoặc deploy lỗi)"""
        try:
            if user.is_superuser:
                cert = SSLCertificate.objects.get(id=cert_id)
            else:
                cert = SSLCertificate.objects.get(id=cert_id, domain__tenant=user.tenant)
        except SSLCertificate.DoesNotExist:
            raise ValidationError("Không tìm thấy chứng chỉ cần xóa.")

        if cert.status == SSLCertificate.STATUS_DEPLOYING:
            raise ValidationError("Hệ thống đang tiến hành deploy, không được phép xóa bản ghi.")

        # Kiểm tra điều kiện: Chưa deploy thành công HOẶC Đã hết hạn
        # Trạng thái chưa deploy thành công bao gồm: pending, valid, invalid, failed
        is_not_deployed = cert.status in [
            SSLCertificate.STATUS_PENDING,
            SSLCertificate.STATUS_VALID,
            SSLCertificate.STATUS_INVALID,
            SSLCertificate.STATUS_FAILED
        ]

        if not (is_not_deployed or cert.is_expired):
            raise ValidationError("Chứng chỉ đang hoạt động và chưa hết hạn, không được phép xóa.")

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