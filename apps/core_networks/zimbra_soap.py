import httpx
import xmltodict
from xml.sax.saxutils import escape
from django.core.exceptions import ValidationError
from loguru import logger


class ZimbraAdminSoapClient:
    def __init__(self, server):
        self.server = server
        self.url = f"https://{server.hostname}:7071/service/admin/soap"
        self.token = None

    def login(self):
        """Đăng nhập vào Zimbra Admin bằng tài khoản Email Admin ứng dụng thông qua HTTPX"""
        # FIX: escape() email/password trước khi nhúng vào XML. Trước đây nối
        # f-string trực tiếp -- nếu password chứa ký tự đặc biệt XML (&, <, >)
        # sẽ làm hỏng cấu trúc SOAP request (gây lỗi parse khó hiểu phía Zimbra),
        # hoặc về lý thuyết có thể bị lợi dụng để chèn thêm node XML (XML injection)
        # nếu giá trị đó do người dùng kiểm soát được.
        safe_email = escape(self.server.zimbra_admin_email or "")
        safe_password = escape(self.server.zimbra_admin_password or "")

        soap_body = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Header>
                <context xmlns="urn:zimbra"/>
            </soap:Header>
            <soap:Body>
                <AuthRequest xmlns="urn:zimbraAdmin">
                    <name>{safe_email}</name>
                    <password>{safe_password}</password>
                </AuthRequest>
            </soap:Body>
        </soap:Envelope>"""

        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}

        with httpx.Client(verify=False, timeout=10.0) as client:
            try:
                response = client.post(self.url, content=soap_body, headers=headers)
                # Không print/log email/password hoặc raw response ra console --
                # log production thường lưu rất lâu và nhiều người đọc được, đây
                # là rò rỉ thông tin nhạy cảm nghiêm trọng. Chỉ log ở mức DEBUG,
                # không có giá trị nhạy cảm.
                logger.debug(f"Zimbra SOAP login attempt for {self.server.hostname} as {self.server.zimbra_admin_email}")

                if response.status_code != 200:
                    raise ValidationError("Xác thực SOAP thất bại. Vui lòng kiểm tra lại Zimbra Admin Email/Password.")

                data = xmltodict.parse(response.text)
                self.token = data['soap:Envelope']['soap:Body']['AuthResponse']['authToken']
            except httpx.RequestError as exc:
                raise ValidationError(f"Không thể kết nối tới cổng 7071 của Zimbra Server {self.server.hostname}: {exc}")
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(f"Lỗi phân tích cú pháp XML từ Zimbra: {str(e)}")

    def domain_exists(self, domain_name: str) -> bool:
        """Kiểm tra tên miền tồn tại trên Zimbra Server"""
        if not self.token:
            self.login()

        soap_body = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Header>
                <context xmlns="urn:zimbra">
                    <authToken>{escape(self.token)}</authToken>
                </context>
            </soap:Header>
            <soap:Body>
                <GetAllDomainsRequest xmlns="urn:zimbraAdmin"/>
            </soap:Body>
        </soap:Envelope>"""

        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}

        with httpx.Client(verify=False, timeout=10.0) as client:
            try:
                response = client.post(self.url, content=soap_body, headers=headers)
                data = xmltodict.parse(response.text)

                domains_response = data['soap:Envelope']['soap:Body']['GetAllDomainsResponse']

                if 'domain' not in domains_response:
                    return False

                domains_list = domains_response['domain']
                if isinstance(domains_list, dict):
                    domains_list = [domains_list]

                for d in domains_list:
                    if d.get('@name') == domain_name:
                        return True
                return False
            except Exception as e:
                logger.warning(f"domain_exists check failed for {domain_name} on {self.server.hostname}: {e}")
                return False

    def create_domain(self, domain_name: str):
        """Tạo mới Domain trên Zimbra Server vật lý thông qua API"""
        if not self.token:
            self.login()

        # FIX: escape domain_name và authToken trước khi nhúng vào XML, cùng lý
        # do với login() ở trên.
        safe_domain_name = escape(domain_name)
        safe_token = escape(self.token)

        soap_body = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Header>
                <context xmlns="urn:zimbra">
                    <authToken>{safe_token}</authToken>
                </context>
            </soap:Header>
            <soap:Body>
                <CreateDomainRequest xmlns="urn:zimbraAdmin">
                    <name>{safe_domain_name}</name>
                </CreateDomainRequest>
            </soap:Body>
        </soap:Envelope>"""

        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}

        with httpx.Client(verify=False, timeout=10.0) as client:
            try:
                response = client.post(self.url, content=soap_body, headers=headers)
                if response.status_code != 200:
                    # Nếu cấu trúc Fault không đúng định dạng mong đợi (KeyError),
                    # vẫn raise ValidationError với message chung thay vì để lỗi 500 lộ traceback.
                    try:
                        data = xmltodict.parse(response.text)
                        reason = data['soap:Envelope']['soap:Body']['soap:Fault']['soap:Reason']['soap:Text']['#text']
                    except (KeyError, Exception):
                        reason = f"Phản hồi không xác định từ Zimbra (HTTP {response.status_code})."
                    raise ValidationError(f"Zimbra không cho phép tạo domain. Lý do: {reason}")
                return True
            except httpx.RequestError as exc:
                raise ValidationError(f"Lỗi kết nối mạng khi tạo domain: {exc}")