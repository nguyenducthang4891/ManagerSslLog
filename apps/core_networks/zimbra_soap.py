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

    # ------------------------------------------------------------------
    # Helpers nội bộ (dùng chung cho các action mailbox bên dưới)
    # ------------------------------------------------------------------
    def _post_soap(self, body_xml: str, *, action_label: str) -> dict:
        """
        Helper chung: tự login nếu chưa có token, gửi SOAP request, parse XML,
        và raise ValidationError với message tiếng Việt thân thiện nếu có lỗi.
        Không log nội dung soap_body/response (có thể chứa email/password/token).
        """
        if not self.token:
            self.login()

        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
        with httpx.Client(verify=False, timeout=15.0) as client:
            try:
                response = client.post(self.url, content=body_xml, headers=headers)
            except httpx.RequestError as exc:
                logger.debug(f"Lỗi kết nối mạng khi {action_label}: {exc}")
                raise ValidationError(f"Lỗi kết nối mạng khi {action_label}: {exc}")
            logger.info(response.text)
            try:
                data = xmltodict.parse(response.text)
            except Exception as e:
                logger.exception(f"Lỗi phân tích cú pháp XML từ Zimbra khi {action_label}: {str(e)}")
                raise ValidationError(f"Lỗi phân tích cú pháp XML từ Zimbra khi {action_label}: {str(e)}")

            if response.status_code != 200:
                reason = self._extract_fault_reason(data, response.status_code)
                raise ValidationError(f"Zimbra từ chối yêu cầu {action_label}. Lý do: {reason}")

            return data

    @staticmethod
    def _extract_fault_reason(data: dict, status_code: int) -> str:
        try:
            return data['soap:Envelope']['soap:Body']['soap:Fault']['soap:Reason']['soap:Text']['#text']
        except Exception:
            return f"Phản hồi không xác định từ Zimbra (HTTP {status_code})."

    @staticmethod
    def _attrs_to_dict(account_node: dict) -> dict:
        """
        Chuyển node <a n="givenName">...</a> (list hoặc dict) trong response
        Zimbra (GetAccountResponse/SearchDirectoryResponse) thành dict đơn giản
        {attr_name: value}. Zimbra trả nhiều <a> trùng tên nếu multi-value --
        ở đây chỉ lấy giá trị đầu tiên vì các field cần (givenName, sn, ...) là single-value.
        """
        attrs = {}
        a_nodes = account_node.get('a', [])
        if isinstance(a_nodes, dict):
            a_nodes = [a_nodes]
        for node in a_nodes:
            if not isinstance(node, dict):
                continue
            name = node.get('@n')
            value = node.get('#text', '')
            if name and name not in attrs:
                attrs[name] = value
        return attrs

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

    # ------------------------------------------------------------------
    # MAILBOX: tìm kiếm & quản lý tài khoản email (GAL / Account)
    # ------------------------------------------------------------------
    def search_account(self, email_query: str, domain_name: str, limit: int = 25, offset: int = 0) -> list[dict]:
        """
        Tìm account theo tài liệu Zimbra Admin API Spec.
        Sử dụng attribute query và domain chuẩn hóa, loại bỏ khoảng trắng dư thừa.

        `offset`: dùng cho phân trang kiểu infinite-scroll phía client -- mỗi
        lần cuộn tới đáy sẽ gọi lại với offset = số record đã tải.
        """
        if not self.token:
            self.login()

        # 1. Làm sạch và trích xuất dữ liệu đầu vào
        safe_token = escape(self.token)
        clean_query = email_query.strip()
        clean_domain = domain_name.strip()

        # 2. Xây dựng LDAP filter AND (&) chuẩn theo RFC 2254
        # Kết hợp điều kiện: Tìm gần đúng email VÀ phải thuộc domain chỉ định
        raw_filter = f"(&(objectClass=zimbraAccount)(mail=*{clean_query}*)(mail=*@{clean_domain}))"

        # 3. Ép escape để biến '&' thành '&amp;' hợp lệ với XML Attribute
        safe_filter = escape(raw_filter)

        # 4. Tạo chuỗi XML liền mạch, phẳng hoàn toàn theo đúng cấu trúc thuộc tính của tài liệu
        soap_body = (
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
            '<soap:Header>'
            '<context xmlns="urn:zimbra">'
            f'<authToken>{safe_token}</authToken>'
            '</context>'
            '</soap:Header>'
            '<soap:Body>'
            f'<SearchDirectoryRequest xmlns="urn:zimbraAdmin" types="accounts" '
            f'limit="{int(limit)}" offset="{int(offset)}" domain="{escape(clean_domain)}" query="{safe_filter}"/>'
            '</soap:Body>'
            '</soap:Envelope>'
        )

        # Gửi request sang helper xử lý SOAP tập trung
        data = self._post_soap(soap_body, action_label="tìm kiếm email")

        try:
            resp = data['soap:Envelope']['soap:Body']['SearchDirectoryResponse']
        except KeyError:
            return []

        if 'account' not in resp:
            return []

        accounts = resp['account']
        if isinstance(accounts, dict):
            accounts = [accounts]

        results = []
        for acc in accounts:
            attrs = self._attrs_to_dict(acc)
            # Theo tài liệu trả về: <account name="{name}" id="{id}">
            attrs['name'] = acc.get('@name', attrs.get('mail', ''))
            attrs['id'] = acc.get('@id', '')
            results.append(attrs)
        return results

    def create_account(self, email: str, password: str, attrs: dict) -> dict:
        """
        Tạo account mới bằng CreateAccountRequest.
        `attrs` là dict {tên_attribute_zimbra: giá_trị} (givenName, sn,
        displayName, zimbraMailQuota, ...). Giá trị rỗng/None bị bỏ qua,
        TRỪ zimbraMailQuota="0" (0 hợp lệ -- nghĩa là không giới hạn dung
        lượng, không được coi là "rỗng" và bỏ qua).
        """
        if not self.token:
            self.login()

        safe_token = escape(self.token)
        safe_email = escape(email.strip())
        safe_password = escape(password)

        a_tags = ""
        for k, v in attrs.items():
            if v is None:
                continue
            if v == "" and k != "zimbraMailQuota":
                continue
            a_tags += f'<a n="{escape(k)}">{escape(str(v))}</a>'

        soap_body = (
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
            '<soap:Header>'
            '<context xmlns="urn:zimbra">'
            f'<authToken>{safe_token}</authToken>'
            '</context>'
            '</soap:Header>'
            '<soap:Body>'
            '<CreateAccountRequest xmlns="urn:zimbraAdmin" '
            f'name="{safe_email}" password="{safe_password}">'
            f'{a_tags}'
            '</CreateAccountRequest>'
            '</soap:Body>'
            '</soap:Envelope>'
        )

        data = self._post_soap(soap_body, action_label=f"tạo tài khoản email {email}")

        try:
            acc = data['soap:Envelope']['soap:Body']['CreateAccountResponse']['account']
        except KeyError:
            raise ValidationError(f"Tạo tài khoản '{email}' thất bại: Zimbra không trả về thông tin account.")

        result = self._attrs_to_dict(acc)
        result['name'] = acc.get('@name', email)
        result['id'] = acc.get('@id', '')
        return result

    def get_account(self, email: str) -> dict:
        """Lấy chi tiết 1 account theo email (GetAccountRequest)."""
        if not self.token:
            self.login()

        safe_token = escape(self.token)
        safe_email = escape(email.strip())

        # Ép chuỗi XML phẳng, sửa lỗi thiếu dấu ngoặc nhọn ở authToken {safe_token}
        soap_body = (
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
            '<soap:Header>'
            '<context xmlns="urn:zimbra">'
            f'<authToken>{safe_token}</authToken>'
            '</context>'
            '</soap:Header>'
            '<soap:Body>'
            '<GetAccountRequest xmlns="urn:zimbraAdmin">'
            f'<account by="name">{safe_email}</account>'
            '</GetAccountRequest>'
            '</soap:Body>'
            '</soap:Envelope>'
        )

        data = self._post_soap(soap_body, action_label=f"lấy thông tin email {email}")

        try:
            acc = data['soap:Envelope']['soap:Body']['GetAccountResponse']['account']
        except KeyError:
            raise ValidationError(f"Không tìm thấy tài khoản email '{email}' trên Zimbra Server.")

        attrs = self._attrs_to_dict(acc)
        attrs['name'] = acc.get('@name', email)
        attrs['id'] = acc.get('@id', '')
        return attrs

    def modify_account(self, email: str, attrs: dict):
        """
        Sửa thông tin profile account (givenName, sn, displayName, title, mobile, ...)
        bằng ModifyAccountRequest. `attrs` là dict {tên_attribute_zimbra: giá_trị}.
        Giá trị rỗng/None sẽ bị bỏ qua (không xóa nhầm attribute khi để trống ô input).
        """
        account = self.get_account(email)
        account_id = account.get('id')
        if not account_id:
            raise ValidationError(f"Không xác định được ID tài khoản '{email}' để chỉnh sửa.")

        a_tags = ""
        for k, v in attrs.items():
            if v is None or v == "":
                continue
            a_tags += f'<a n="{escape(k)}">{escape(str(v))}</a>'

        if not a_tags:
            return  # không có gì để cập nhật

        soap_body = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Header>
                <context xmlns="urn:zimbra">
                    <authToken>{escape(self.token) if self.token else ''}</authToken>
                </context>
            </soap:Header>
            <soap:Body>
                <ModifyAccountRequest xmlns="urn:zimbraAdmin">
                    <id>{escape(account_id)}</id>
                    {a_tags}
                </ModifyAccountRequest>
            </soap:Body>
        </soap:Envelope>"""

        self._post_soap(soap_body, action_label=f"cập nhật thông tin email {email}")

    def set_account_status(self, email: str, status: str):
        """
        Đổi trạng thái account: active | locked | closed (zimbraAccountStatus).
        Lưu ý: 'closed' KHÔNG xóa mailbox, chỉ khóa hoàn toàn không cho gửi/nhận/login,
        khác với delete_account() (xóa vĩnh viễn).
        """
        allowed = {"active", "locked", "closed"}
        if status not in allowed:
            raise ValidationError(f"Trạng thái '{status}' không hợp lệ (chỉ chấp nhận: {', '.join(allowed)}).")
        self.modify_account(email, {"zimbraAccountStatus": status})

    def set_password(self, email: str, new_password: str):
        """Đặt lại mật khẩu account (SetPasswordRequest) -- dùng cho chức năng Reset Password."""
        account = self.get_account(email)
        account_id = account.get('id')
        if not account_id:
            raise ValidationError(f"Không xác định được ID tài khoản '{email}' để đặt lại mật khẩu.")

        soap_body = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Header>
                <context xmlns="urn:zimbra">
                    <authToken>{escape(self.token) if self.token else ''}</authToken>
                </context>
            </soap:Header>
            <soap:Body>
                <SetPasswordRequest xmlns="urn:zimbraAdmin" id="{escape(account_id)}" newPassword="{escape(new_password)}"/>
            </soap:Body>
        </soap:Envelope>"""

        self._post_soap(soap_body, action_label=f"đặt lại mật khẩu cho email {email}")

    def rename_account(self, old_email: str, new_email: str):
        """Đổi tên (đổi địa chỉ) account bằng RenameAccountRequest."""
        account = self.get_account(old_email)
        account_id = account.get('id')
        if not account_id:
            raise ValidationError(f"Không xác định được ID tài khoản '{old_email}' để đổi tên.")

        soap_body = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Header>
                <context xmlns="urn:zimbra">
                    <authToken>{escape(self.token) if self.token else ''}</authToken>
                </context>
            </soap:Header>
            <soap:Body>
                <RenameAccountRequest xmlns="urn:zimbraAdmin" id="{escape(account_id)}" newName="{escape(new_email)}"/>
            </soap:Body>
        </soap:Envelope>"""

        self._post_soap(soap_body, action_label=f"đổi tên email {old_email} thành {new_email}")

    def delete_account(self, email: str):
        """Xóa vĩnh viễn account khỏi Zimbra (DeleteAccountRequest) -- KHÔNG thể khôi phục."""
        account = self.get_account(email)
        account_id = account.get('id')
        if not account_id:
            raise ValidationError(f"Không xác định được ID tài khoản '{email}' để xóa.")

        soap_body = f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
            <soap:Header>
                <context xmlns="urn:zimbra">
                    <authToken>{escape(self.token) if self.token else ''}</authToken>
                </context>
            </soap:Header>
            <soap:Body>
                <DeleteAccountRequest xmlns="urn:zimbraAdmin" id="{escape(account_id)}"/>
            </soap:Body>
        </soap:Envelope>"""

        self._post_soap(soap_body, action_label=f"xóa email {email}")

    def get_backup_download_url(self, email: str) -> str:
        """
        URL tải backup mailbox dạng .tgz, dùng HTTP Basic Auth (không qua SOAP
        token) theo định dạng: https://<host>:7071/home/<email>/?fmt=tgz
        Việc gọi thực tế (stream file) do view xử lý để có thể trả thẳng cho
        client mà không load toàn bộ file vào RAM.
        """
        return f"https://{self.server.hostname}:7071/home/{email}/?fmt=tgz"