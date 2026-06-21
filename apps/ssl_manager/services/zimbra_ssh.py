import io
import paramiko
from django.utils import timezone
from apps.ssl_manager.models import SSLCertificate, DeployHistory
from io import StringIO

from apps.utils.clean import clean_certificate_content


def _load_private_key(key_text: str):
    """
    Hỗ trợ nhiều loại private key (RSA/Ed25519/ECDSA/DSS) để tránh deploy fail.
    """
    key_classes = [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]
    last_error = None
    for key_cls in key_classes:
        try:
            return key_cls.from_private_key(StringIO(key_text))
        except paramiko.SSHException as e:
            last_error = e
            continue
    raise paramiko.SSHException(f"Không thể nhận diện loại Private Key: {last_error}")


class ZimbraDeployService:
    def __init__(self, cert_id: int, triggered_by=None):
        self.cert = SSLCertificate.objects.get(id=cert_id)
        self.server = self.cert.domain.server
        self.log_content = self.cert.deploy_log or ""
        self.triggered_by = triggered_by
        self.history_record = None
        self.ssh = None

    def _log(self, message):
        """Ghi log vào chuỗi và đồng bộ xuống DB phục vụ Real-time Polling"""
        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {message}\n"

        self.cert.refresh_from_db(fields=['deploy_log'])
        self.cert.deploy_log += formatted_message
        self.cert.save(update_fields=['deploy_log'])

    def _connect(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if self.server.ssh_key:
            pkey = _load_private_key(self.server.ssh_key)
            self.ssh.connect(self.server.hostname, port=self.server.port, username=self.server.username,
                             pkey=pkey, timeout=30, banner_timeout=30, auth_timeout=30)
        else:
            self.ssh.connect(self.server.hostname, port=self.server.port, username=self.server.username,
                             password=self.server.ssh_password, timeout=30, banner_timeout=30, auth_timeout=30)

    def _exec(self, command: str, timeout: int = 300) -> dict:
        """Chạy lệnh và trả về exit_status THẬT"""
        stdin, stdout, stderr = self.ssh.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        return {'exit_status': exit_status, 'output': out, 'error': err}

    def _exec_as_zimbra(self, command: str, timeout: int = 300) -> dict:
        return self._exec(f"su - zimbra -c '{command}'", timeout=timeout)

    def execute_deploy(self):
        self.history_record = DeployHistory.objects.create(
            certificate=self.cert,
            triggered_by=self.triggered_by,
            status=DeployHistory.STATUS_FAILED,  # tạm, sẽ update ở finally
            started_at=timezone.now(),
        )
        self.cert.status = SSLCertificate.STATUS_DEPLOYING
        self.cert.deploy_log = ""
        self.cert.save(update_fields=['status', 'deploy_log'])

        domain_name = self.cert.domain.name
        domain_safe = domain_name.replace('/', '_')

        # Đường dẫn thư mục lưu chứng chỉ theo domain ảo giống ssl.py
        cert_dir = f"{self.server.zimbra_home}/ssl/zimbra/commercial/{domain_safe}"
        timestamp_str = timezone.now().strftime('%Y%m%d_%H%M%S')
        backup_directory = f"{cert_dir}.backup.{timestamp_str}"

        # Giả định cấu hình Virtual Hostname mặc định giống nghiệp vụ ssl.py
        virtual_hostname = f"mail.{domain_name}"
        # if domain_name == 'mailpoc.cpt.gov.vn':
        #     virtual_hostname = "mailpoc.cpt.gov.vn"

        try:
            self._log(f"Bắt đầu kết nối tới Zimbra: {self.server.hostname} làm user root")
            self._connect()
            self._log("Kết nối SSH thành công. Đang kiểm tra trạng thái Zimbra...")

            # ===== BƯỚC 1: Kiểm tra Zimbra installation =====
            check_zimbra = self._exec_as_zimbra(f"{self.server.zimbra_home}/bin/zmcontrol status")
            if check_zimbra['exit_status'] != 0:
                raise Exception(f"Zimbra không hoạt động hoặc không thể truy cập: {check_zimbra['error']}")

            # Lấy IP của server để làm Virtual IP nếu cần
            ip_result = self._exec("hostname -I | awk '{print $1}'")
            virtual_ip = ip_result['output'].strip() or "127.0.0.1"

            # ===== BƯỚC 2: Backup thư mục cert cũ nếu tồn tại =====
            check_dir = self._exec(f"test -d {cert_dir} && echo 'exists' || echo 'not exists'")
            if 'exists' in check_dir['output']:
                self._exec(f"cp -r {cert_dir} {backup_directory}")
                self._log(f"Đã tạo backup thư mục cũ tại: {backup_directory}")

            # ===== BƯỚC 3: Tạo thư mục chứa cert mới =====
            self._exec(f"mkdir -p {cert_dir}")

            # ===== BƯỚC 4: Upload các file chứng chỉ lên Server =====
            self._log("Đang tải các file chứng chỉ lên máy chủ...")
            sftp = self.ssh.open_sftp()

            cert_file = f"{cert_dir}/{domain_name}.crt"
            key_file = f"{cert_dir}/{domain_name}.key"
            ca_file = f"{cert_dir}/{domain_name}_ca.crt"
            bundle_file = f"{cert_dir}/{domain_name}.bundle"

            # Đọc và làm sạch nội dung Cert & Key
            clean_cert = clean_certificate_content(self.cert.server_cert.read())
            clean_key = clean_certificate_content(self.cert.private_key.read())

            # Upload cert & key đã được làm sạch hoàn toàn
            with sftp.file(cert_file, "wb") as f:
                f.write(clean_cert)
            with sftp.file(key_file, "wb") as f:
                f.write(clean_key)

            # Đọc và làm sạch chuỗi CA Chain (Gộp Inter + Root nếu có)
            ca_parts = []
            if self.cert.inter_cert:
                inter_data = self.cert.inter_cert.read()
                if inter_data:
                    ca_parts.append(clean_certificate_content(inter_data).decode('utf-8').strip())

            if self.cert.root_cert:
                root_data = self.cert.root_cert.read()
                if root_data:
                    ca_parts.append(clean_certificate_content(root_data).decode('utf-8').strip())

            has_ca = False
            if ca_parts:
                # Ghép nối các CA sạch sẽ bằng đúng 1 dấu xuống dòng
                ca_chain_str = "\n".join(ca_parts).strip() + "\n"
                with sftp.file(ca_file, "wb") as f:
                    f.write(ca_chain_str.encode('utf-8'))
                has_ca = True
            else:
                self._exec(f"touch {ca_file}")

            sftp.close()

            # Set quyền và owner cho user zimbra
            self._exec(f"chmod -R 777 {cert_dir} && chown -R zimbra:zimbra {cert_dir}")
            self._log("Đã upload chứng chỉ chuẩn hóa format thành công.")


            # ===== BƯỚC 5: Cấu hình /etc/hosts và Zimbra Virtual Settings =====
            self._log(f"Cấu hình file /etc/hosts với {virtual_ip} -> {virtual_hostname}")
            check_hosts = self._exec(f"grep -q '{virtual_ip}.*{virtual_hostname}' /etc/hosts")
            if check_hosts['exit_status'] != 0:
                self._exec(f"echo '{virtual_ip}  {virtual_hostname}' >> /etc/hosts")

            self._log(f"Cấu hình Zimbra Virtual Domain cho {domain_name}...")
            md_cmd = f"{self.server.zimbra_home}/bin/zmprov md {domain_name} zimbraVirtualHostname {virtual_hostname} zimbraVirtualIPAddress {virtual_ip}"
            self._exec_as_zimbra(md_cmd)

            # ===== BƯỚC 6: VERIFY Chứng chỉ qua zmcertmgr =====
            self._log("Tiến hành kiểm tra (Verify) chứng chỉ bằng zmcertmgr...")
            verify_cmd = f"cd {cert_dir} && {self.server.zimbra_home}/bin/zmcertmgr verifycrt comm"
            # Lưu ý: zmcertmgr verifycrt comm trong thư mục domain yêu cầu file phải đặt tên đúng cấu trúc mặc định hoặc truyền tham số.
            # Dựa theo ssl.py, lệnh chạy trực tiếp là:
            verify_result = self._exec_as_zimbra(
                f"cd {cert_dir} && {self.server.zimbra_home}/bin/zmcertmgr verifycrt comm {key_file} {cert_file} {ca_file}")
            self._log(f"[Zimbra Verify Output]: {verify_result['output']}")

            if verify_result['exit_status'] != 0:
                raise Exception(f"Verify thất bại: {verify_result['output'] or verify_result['error']}")

            # ===== BƯỚC 7: Tạo file bundle tổng hợp =====
            self._log("Tạo file bundle tổng hợp từ Cert và CA sạch...")

            cert_str = clean_cert.decode('utf-8').strip()
            if has_ca:
                bundle_content = f"{cert_str}\n{ca_chain_str.strip()}\n"
            else:
                bundle_content = f"{cert_str}\n"

            sftp = self.ssh.open_sftp()
            with sftp.file(bundle_file, "wb") as f:
                f.write(bundle_content.encode('utf-8'))
            sftp.close()

            self._exec(f"chmod 777 {bundle_file} && chown zimbra:zimbra {bundle_file}")


            # ===== BƯỚC 8: Lưu chứng chỉ (savecrt) bằng zmdomaincertmgr =====
            self._log("Đang lưu chứng chỉ vào cấu hình Domain bằng zmdomaincertmgr...")
            savecrt_cmd = f"cd {cert_dir} && {self.server.zimbra_home}/libexec/zmdomaincertmgr savecrt {domain_name} {bundle_file} {key_file}"
            save_res = self._exec_as_zimbra(savecrt_cmd, timeout=120)
            self._log(f"[Zimbra Savecrt Output]: {save_res['output']}")
            if save_res['exit_status'] != 0:
                raise Exception(f"Lưu chứng chỉ (savecrt) thất bại: {save_res['output']}")

            # ===== BƯỚC 9: Triển khai (deploycrts) bằng zmdomaincertmgr =====
            self._log("Đang tiến hành deploy chứng chỉ đa tên miền (deploycrts)...")
            deploy_res = self._exec_as_zimbra(f"{self.server.zimbra_home}/libexec/zmdomaincertmgr deploycrts",
                                              timeout=180)
            self._log(f"[Zimbra Deploycrts Output]: {deploy_res['output']}")
            if deploy_res['exit_status'] != 0:
                raise Exception(f"Deploycrts thất bại: {deploy_res['output']}")

            # ===== BƯỚC 10: Kích hoạt SNI trên Zimbra Proxy =====
            self._log("Kiểm tra và kích hoạt SNI Reverse Proxy...")
            sni_check = self._exec_as_zimbra(f"{self.server.zimbra_home}/bin/zmprov gcf zimbraReverseProxySNIEnabled")
            if 'TRUE' not in sni_check['output']:
                self._exec_as_zimbra(f"{self.server.zimbra_home}/bin/zmprov mcf zimbraReverseProxySNIEnabled TRUE")

            # ===== BƯỚC 11: Khởi động lại dịch vụ Proxy (Không gây sập mail hoàn toàn) =====
            self._log("Đang khởi động lại Zimbra Proxy để áp dụng chứng chỉ mới...")
            restart_res = self._exec_as_zimbra(f"{self.server.zimbra_home}/bin/zmproxyctl restart", timeout=300)
            self._log(f"[Zimbra Proxy Restart Output]: {restart_res['output']}")

            # ===== BƯỚC 12: Kiểm tra kết nối thực tế cuối cùng =====
            test_cmd = f"echo | openssl s_client -connect {virtual_hostname}:443 -servername {virtual_hostname} 2>/dev/null | openssl x509 -noout -subject -dates"
            test_res = self._exec(test_cmd)
            self._log(f"[OpenSSL Verification Output]:\n{test_res['output']}")

            # Hoàn thành thành công
            self.cert.status = SSLCertificate.STATUS_DEPLOYED
            self.cert.deployed_at = timezone.now()
            self._log(f">>> ĐÃ DEPLOY SSL CHO DOMAIN {domain_name} THÀNH CÔNG HOÀN TOÀN! <<<")

        except Exception as e:
            self.cert.status = SSLCertificate.STATUS_FAILED
            error_msg = str(e)
            self._log(f">>> TRIỂN KHAI THẤT BẠI: {error_msg}")

            # Khôi phục dữ liệu từ backup nếu gặp lỗi giữa chừng
            try:
                check_backup = self._exec(f"test -d {backup_directory} && echo 'exists' || echo 'not exists'")
                if 'exists' in check_backup['output']:
                    self._log("Đang tiến hành khôi phục lại cấu hình chứng chỉ cũ từ bản backup...")
                    self._exec(f"rm -rf {cert_dir}")
                    self._exec(f"mv {backup_directory} {cert_dir}")
                    self._log("✓ Khôi phục bản backup thành công.")
            except Exception as rollback_err:
                self._log(f"⚠️ Khôi phục backup thất bại: {rollback_err}")

        finally:
            self.cert.save(update_fields=['status', 'deployed_at'])

            # MỚI: chốt lại record lịch sử với kết quả cuối cùng + toàn bộ log
            # snapshot (deploy_log tại thời điểm này), để sau này deploy lại
            # (làm deploy_log bị reset) vẫn xem lại được log của lần này.
            self.cert.refresh_from_db(fields=['deploy_log'])
            if self.history_record:
                self.history_record.status = (
                    DeployHistory.STATUS_SUCCESS if self.cert.status == SSLCertificate.STATUS_DEPLOYED
                    else DeployHistory.STATUS_FAILED
                )
                self.history_record.log_snapshot = self.cert.deploy_log
                self.history_record.finished_at = timezone.now()
                self.history_record.save(update_fields=['status', 'log_snapshot', 'finished_at'])

            if self.ssh:
                self.ssh.close()