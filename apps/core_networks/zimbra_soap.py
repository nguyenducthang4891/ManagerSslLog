import httpx
import xmltodict
from xml.sax.saxutils import escape
from django.core.exceptions import ValidationError
from django.core.cache import cache
from loguru import logger

# ----------------------------------------------------------------------
# Tối ưu hiệu năng kết nối:
#
# 1. SHARED HTTP CLIENT (module-level): httpx.Client tự quản lý connection
#    pool theo từng host, nên 1 client dùng chung an toàn cho nhiều Zimbra
#    server khác nhau. Tránh việc mở/đóng TCP+TLS handshake mới cho MỖI
#    SOAP request -- trước đây mỗi lần gọi self.login()/_post_soap()/
#    domain_exists()/create_domain() đều "with httpx.Client(...)" riêng,
#    rất lãng phí khi có N+1 calls liên tiếp (modify/set_password/rename/
#    delete đều phải get_account() trước rồi mới gọi action chính).
#    httpx.Client giữ keep-alive connections trong pool, tái dùng giữa các
#    lệnh gọi liên tiếp tới cùng 1 host.
#
# 2. TOKEN CACHE (Django cache / Redis): authToken Zimbra Admin có hiệu
#    lực dài (mặc định 12h trên Zimbra), nhưng trước đây mỗi instance
#    ZimbraAdminSoapClient (tạo mới ở mỗi request Django, xem
#    services.py::_get_client_for_domain) đều phải login() lại từ đầu --
#    tức là MỌI thao tác mailbox (search, sửa, ...) đều cộng thêm 1 lượt
#    AuthRequest. Cache token theo server (qua Redis, chia sẻ giữa các
#    worker Gunicorn/Daphne) giúp bỏ qua hầu hết các lượt login() lặp lại.
#    TTL cache đặt NGẮN HƠN thời hạn thật của token Zimbra để tránh dùng
#    token đã bị Zimbra revoke (ví dụ do đổi mật khẩu admin) mà cache vẫn
#    còn -- nếu Zimbra vẫn từ chối, _post_soap() sẽ tự re-login và retry
#    1 lần (xem _post_soap()).
# ----------------------------------------------------------------------
_HTTP_CLIENT = httpx.Client(verify=False, timeout=15.0)

TOKEN_CACHE_PREFIX = "zimbra_soap_token"
TOKEN_CACHE_TTL_SECONDS = 10 * 60 * 60  # 10h, ngắn hơn hạn thật ~12h của Zimbra


class ZimbraAdminSoapClient:
    """
    Client gọi Zimbra Admin SOAP API (cổng 7071).

    Quy ước style trong file này (để nhất quán, dễ maintain):
    - Mọi soap_body đều build bằng chuỗi nối '...' (không dùng f-string đa
      dòng) để tránh lỗi thụt lề/indent vô tình lọt vào nội dung XML.
    - Mọi giá trị động nhúng vào XML (token, email, password, id, ...) đều
      phải escape() trước -- không có ngoại lệ.
    - Các hàm thao tác trên 1 account theo email (modify/set_password/
      rename/delete) đều resolve email -> id qua _resolve_account_id() rồi
      mới gọi action, để dùng chung 1 nơi xử lý lỗi "không tìm thấy account".
    """

    def __init__(self, server):
        self.server = server
        self.url = f"https://{server.hostname}:7071/service/admin/soap"
        self.token = None

    @property
    def _token_cache_key(self) -> str:
        # Cache theo server.id (ổn định hơn hostname nếu hostname có thể đổi).
        return f"{TOKEN_CACHE_PREFIX}:{self.server.id}"

    # ------------------------------------------------------------------
    # Helpers nội bộ (dùng chung cho các action mailbox bên dưới)
    # ------------------------------------------------------------------
    def _auth_token_tag(self) -> str:
        """<authToken>...</authToken> đã escape, dùng chung cho mọi soap:Header."""
        return f"<authToken>{escape(self.token) if self.token else ''}</authToken>"

    def _envelope(self, body_inner: str) -> str:
        """
        Bọc `body_inner` (nội dung trong <soap:Body>) vào khung Envelope +
        Header (kèm authToken) chuẩn, dùng chung cho mọi request cần xác thực.
        Tự lấy token từ cache (nếu instance chưa có), hoặc login() nếu cache
        cũng không có.
        """
        self._ensure_token()

        return (
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
            "<soap:Header>"
            '<context xmlns="urn:zimbra">'
            + self._auth_token_tag() +
            "</context>"
            "</soap:Header>"
            "<soap:Body>"
            + body_inner +
            "</soap:Body>"
            "</soap:Envelope>"
        )

    def _ensure_token(self):
        """
        Đảm bảo self.token có giá trị: ưu tiên token đã có trên instance,
        sau đó thử lấy từ cache chia sẻ (Redis), cuối cùng mới login() thật
        (gọi AuthRequest tới Zimbra) nếu không có ở cả 2 nơi trên.
        """
        if self.token:
            return
        cached_token = cache.get(self._token_cache_key)
        if cached_token:
            self.token = cached_token
            return
        self.login()

    def _post_soap(self, body_xml: str, *, action_label: str, _retrying: bool = False) -> dict:
        """
        Helper chung: gửi SOAP request (dùng shared connection pool), parse
        XML, và raise ValidationError với message tiếng Việt thân thiện nếu
        có lỗi. Không log nội dung soap_body/response (có thể chứa
        email/password/token).

        Nếu Zimbra từ chối vì lý do xác thực (token cache đã lệch so với
        thực tế trên Zimbra -- ví dụ admin đổi mật khẩu, hoặc token bị
        revoke sớm hơn TTL cache), tự động login() lại 1 lần và retry, để
        không phải fail cứng người dùng vì lý do hạ tầng nội bộ.
        """
        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
        try:
            response = _HTTP_CLIENT.post(self.url, content=body_xml, headers=headers)
        except httpx.RequestError as exc:
            logger.debug(f"Lỗi kết nối mạng khi {action_label}: {exc}")
            raise ValidationError(f"Lỗi kết nối mạng khi {action_label}: {exc}")

        try:
            data = xmltodict.parse(response.text)
        except Exception as e:
            logger.exception(f"Lỗi phân tích cú pháp XML từ Zimbra khi {action_label}: {str(e)}")
            raise ValidationError(f"Lỗi phân tích cú pháp XML từ Zimbra khi {action_label}: {str(e)}")

        if response.status_code != 200:
            reason = self._extract_fault_reason(data, response.status_code)

            if not _retrying and self._looks_like_auth_error(data):
                # Token cache có thể đã lệch (Zimbra revoke sớm hơn TTL) --
                # xóa cache, login() lấy token mới, và thử lại đúng 1 lần.
                logger.debug(f"Token có thể đã hết hạn khi {action_label}, đang login lại để retry.")
                cache.delete(self._token_cache_key)
                self.token = None
                self.login()
                retried_body = self._reissue_with_fresh_token(body_xml)
                return self._post_soap(retried_body, action_label=action_label, _retrying=True)

            logger.warning(
                f"Zimbra SOAP trả lỗi khi {action_label} "
                f"(HTTP {response.status_code}): {reason}"
            )
            raise ValidationError(f"Zimbra từ chối yêu cầu {action_label}. Lý do: {reason}")

        return data

    @staticmethod
    def _looks_like_auth_error(data: dict) -> bool:
        """Nhận diện lỗi liên quan xác thực (token hết hạn/không hợp lệ) từ Fault code Zimbra."""
        try:
            fault_code = data['soap:Envelope']['soap:Body']['soap:Fault']['soap:Detail']['Error']['Code']
        except Exception:
            return False
        return fault_code in ("soap:auth.AUTH_EXPIRED", "soap:auth.AUTH_REQUIRED")

    def _reissue_with_fresh_token(self, old_body_xml: str) -> str:
        """
        Thay <authToken>...</authToken> cũ trong soap_body đã build sẵn
        bằng token mới (vừa login() lại), để không phải build lại toàn bộ
        body từ đầu khi retry.
        """
        import re
        return re.sub(
            r"<authToken>.*?</authToken>",
            self._auth_token_tag(),
            old_body_xml,
            count=1,
        )

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
        Zimbra (GetAccountResponse/SearchDirectoryResponse/CreateAccountResponse)
        thành dict đơn giản {attr_name: value}. Zimbra trả nhiều <a> trùng tên
        nếu multi-value -- ở đây chỉ lấy giá trị đầu tiên vì các field cần
        (givenName, sn, ...) là single-value.
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

    @staticmethod
    def _node_to_account_dict(acc: dict, fallback_name: str = "") -> dict:
        """Gộp _attrs_to_dict() + @name/@id -- dùng chung cho get/create/search account."""
        attrs = ZimbraAdminSoapClient._attrs_to_dict(acc)
        attrs['name'] = acc.get('@name', fallback_name)
        attrs['id'] = acc.get('@id', '')
        return attrs

    def _resolve_account_id(self, email: str, *, action_desc: str) -> str:
        """
        Lấy account id từ email, dùng chung cho mọi action cần id
        (modify/set_password/rename/delete). Raise lỗi tiếng Việt thống nhất
        nếu không tìm thấy.
        """
        account = self.get_account(email)
        account_id = account.get('id')
        if not account_id:
            raise ValidationError(f"Không xác định được ID tài khoản '{email}' để {action_desc}.")
        return account_id

    @staticmethod
    def _build_a_tags(attrs: dict, *, zero_is_valid: tuple = ()) -> str:
        """
        Build chuỗi các <a n="...">...</a> từ dict attrs.
        Giá trị None hoặc "" bị bỏ qua (không xóa nhầm attribute khi để
        trống ô input) -- TRỪ các key trong `zero_is_valid` khi giá trị
        chính là "0" (ví dụ zimbraMailQuota="0" nghĩa là không giới hạn
        dung lượng, đây là giá trị hợp lệ cần gửi đi, không phải "rỗng").
        """
        a_tags = ""
        for k, v in attrs.items():
            if v is None:
                continue
            if v == "" and k not in zero_is_valid:
                continue
            a_tags += f'<a n="{escape(k)}">{escape(str(v))}</a>'
        return a_tags

    # ------------------------------------------------------------------
    # AUTH
    # ------------------------------------------------------------------
    def login(self):
        """
        Đăng nhập vào Zimbra Admin bằng tài khoản Email Admin ứng dụng.
        Sau khi login thành công, lưu token vào cache chia sẻ (Redis) để
        các instance/worker khác tái dùng, tránh phải AuthRequest lại.
        """
        # FIX: escape() email/password trước khi nhúng vào XML. Trước đây nối
        # f-string trực tiếp -- nếu password chứa ký tự đặc biệt XML (&, <, >)
        # sẽ làm hỏng cấu trúc SOAP request (gây lỗi parse khó hiểu phía Zimbra),
        # hoặc về lý thuyết có thể bị lợi dụng để chèn thêm node XML (XML injection)
        # nếu giá trị đó do người dùng kiểm soát được.
        safe_email = escape(self.server.zimbra_admin_email or "")
        safe_password = escape(self.server.zimbra_admin_password or "")

        soap_body = (
            '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
            "<soap:Header>"
            '<context xmlns="urn:zimbra"/>'
            "</soap:Header>"
            "<soap:Body>"
            '<AuthRequest xmlns="urn:zimbraAdmin">'
            f"<name>{safe_email}</name>"
            f"<password>{safe_password}</password>"
            "</AuthRequest>"
            "</soap:Body>"
            "</soap:Envelope>"
        )

        headers = {"Content-Type": "application/soap+xml; charset=utf-8"}

        try:
            response = _HTTP_CLIENT.post(self.url, content=soap_body, headers=headers)
            # Không print/log email/password hoặc raw response ra console --
            # log production thường lưu rất lâu và nhiều người đọc được, đây
            # là rò rỉ thông tin nhạy cảm nghiêm trọng. Chỉ log ở mức DEBUG,
            # không có giá trị nhạy cảm.
            logger.debug(f"Zimbra SOAP login attempt for {self.server.hostname} as {self.server.zimbra_admin_email}")

            if response.status_code != 200:
                logger.warning(
                    f"Zimbra SOAP login thất bại cho {self.server.hostname} (HTTP {response.status_code})"
                )
                raise ValidationError("Xác thực SOAP thất bại. Vui lòng kiểm tra lại Zimbra Admin Email/Password.")

            data = xmltodict.parse(response.text)
            auth_resp = data['soap:Envelope']['soap:Body']['AuthResponse']
            self.token = auth_resp['authToken']

            # Zimbra trả `lifetime` (ms) = thời hạn thật của token. Dùng giá
            # trị này (trừ biên an toàn) để set TTL cache chính xác hơn là
            # đoán cứng; nếu Zimbra không trả field này, fallback hằng số.
            ttl_seconds = TOKEN_CACHE_TTL_SECONDS
            lifetime_ms = auth_resp.get('lifetime')
            if lifetime_ms:
                try:
                    # Trừ 5 phút biên an toàn để cache luôn hết hạn trước token thật.
                    ttl_seconds = max(60, int(lifetime_ms) // 1000 - 300)
                except (TypeError, ValueError):
                    pass

            cache.set(self._token_cache_key, self.token, timeout=ttl_seconds)
        except httpx.RequestError as exc:
            raise ValidationError(f"Không thể kết nối tới cổng 7071 của Zimbra Server {self.server.hostname}: {exc}")
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Lỗi phân tích cú pháp XML từ Zimbra: {str(e)}")

    # ------------------------------------------------------------------
    # DOMAIN
    # ------------------------------------------------------------------
    def domain_exists(self, domain_name: str) -> bool:
        """Kiểm tra tên miền tồn tại trên Zimbra Server. Trả về False nếu có lỗi (không raise)."""
        soap_body = self._envelope('<GetAllDomainsRequest xmlns="urn:zimbraAdmin"/>')

        try:
            data = self._post_soap(soap_body, action_label="kiểm tra tên miền")
        except ValidationError as e:
            logger.warning(f"domain_exists check failed for {domain_name} on {self.server.hostname}: {e}")
            return False

        try:
            domains_response = data['soap:Envelope']['soap:Body']['GetAllDomainsResponse']
            if 'domain' not in domains_response:
                return False
            domains_list = domains_response['domain']
            if isinstance(domains_list, dict):
                domains_list = [domains_list]
            return any(d.get('@name') == domain_name for d in domains_list)
        except Exception as e:
            logger.warning(f"domain_exists parse failed for {domain_name} on {self.server.hostname}: {e}")
            return False

    def create_domain(self, domain_name: str):
        """Tạo mới Domain trên Zimbra Server vật lý thông qua API"""
        # FIX: escape domain_name trước khi nhúng vào XML, cùng lý do với
        # login() ở trên.
        safe_domain_name = escape(domain_name)

        soap_body = self._envelope(
            '<CreateDomainRequest xmlns="urn:zimbraAdmin">'
            f"<name>{safe_domain_name}</name>"
            "</CreateDomainRequest>"
        )

        self._post_soap(soap_body, action_label=f"tạo domain {domain_name}")
        return True

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
        clean_query = email_query.strip()
        clean_domain = domain_name.strip()

        # Xây dựng LDAP filter AND (&) chuẩn theo RFC 2254. Kết hợp điều
        # kiện: tìm gần đúng email VÀ phải thuộc domain chỉ định.
        raw_filter = f"(&(objectClass=zimbraAccount)(mail=*{clean_query}*)(mail=*@{clean_domain}))"
        safe_filter = escape(raw_filter)

        soap_body = self._envelope(
            f'<SearchDirectoryRequest xmlns="urn:zimbraAdmin" types="accounts" '
            f'limit="{int(limit)}" offset="{int(offset)}" domain="{escape(clean_domain)}" query="{safe_filter}"/>'
        )

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

        return [
            self._node_to_account_dict(acc, fallback_name=self._attrs_to_dict(acc).get('mail', ''))
            for acc in accounts
        ]

    def create_account(self, email: str, password: str, attrs: dict) -> dict:
        """
        Tạo account mới bằng CreateAccountRequest.
        `attrs` là dict {tên_attribute_zimbra: giá_trị} (givenName, sn,
        displayName, zimbraMailQuota, ...). Giá trị rỗng/None bị bỏ qua,
        TRỪ zimbraMailQuota="0" (0 hợp lệ -- nghĩa là không giới hạn dung
        lượng, không được coi là "rỗng" và bỏ qua).
        """
        safe_email = escape(email.strip())
        safe_password = escape(password)
        a_tags = self._build_a_tags(attrs, zero_is_valid=("zimbraMailQuota",))

        soap_body = self._envelope(
            f'<CreateAccountRequest xmlns="urn:zimbraAdmin" name="{safe_email}" password="{safe_password}">'
            f"{a_tags}"
            "</CreateAccountRequest>"
        )

        data = self._post_soap(soap_body, action_label=f"tạo tài khoản email {email}")

        try:
            acc = data['soap:Envelope']['soap:Body']['CreateAccountResponse']['account']
        except KeyError:
            raise ValidationError(f"Tạo tài khoản '{email}' thất bại: Zimbra không trả về thông tin account.")

        return self._node_to_account_dict(acc, fallback_name=email)

    def get_account(self, email: str) -> dict:
        """Lấy chi tiết 1 account theo email (GetAccountRequest)."""
        safe_email = escape(email.strip())

        soap_body = self._envelope(
            '<GetAccountRequest xmlns="urn:zimbraAdmin">'
            f'<account by="name">{safe_email}</account>'
            "</GetAccountRequest>"
        )

        data = self._post_soap(soap_body, action_label=f"lấy thông tin email {email}")

        try:
            acc = data['soap:Envelope']['soap:Body']['GetAccountResponse']['account']
        except KeyError:
            raise ValidationError(f"Không tìm thấy tài khoản email '{email}' trên Zimbra Server.")

        return self._node_to_account_dict(acc, fallback_name=email)

    def modify_account(self, email: str, attrs: dict):
        """
        Sửa thông tin profile account (givenName, sn, displayName, title,
        mobile, zimbraMailQuota, ...) bằng ModifyAccountRequest.
        `attrs` là dict {tên_attribute_zimbra: giá_trị}. Giá trị None hoặc
        chuỗi rỗng "" sẽ bị bỏ qua (không xóa nhầm attribute khi để trống ô
        input). Lưu ý: "0" KHÔNG bị coi là rỗng nên vẫn được gửi đi -- ví dụ
        zimbraMailQuota="0" (không giới hạn dung lượng) vẫn áp dụng đúng.
        """
        account_id = self._resolve_account_id(email, action_desc="chỉnh sửa")

        a_tags = self._build_a_tags(attrs)
        if not a_tags:
            return  # không có gì để cập nhật

        soap_body = self._envelope(
            '<ModifyAccountRequest xmlns="urn:zimbraAdmin">'
            f"<id>{escape(account_id)}</id>"
            f"{a_tags}"
            "</ModifyAccountRequest>"
        )

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
        account_id = self._resolve_account_id(email, action_desc="đặt lại mật khẩu")

        soap_body = self._envelope(
            f'<SetPasswordRequest xmlns="urn:zimbraAdmin" id="{escape(account_id)}" '
            f'newPassword="{escape(new_password)}"/>'
        )

        self._post_soap(soap_body, action_label=f"đặt lại mật khẩu cho email {email}")

    def rename_account(self, old_email: str, new_email: str):
        """Đổi tên (đổi địa chỉ) account bằng RenameAccountRequest."""
        account_id = self._resolve_account_id(old_email, action_desc="đổi tên")

        soap_body = self._envelope(
            f'<RenameAccountRequest xmlns="urn:zimbraAdmin" id="{escape(account_id)}" '
            f'newName="{escape(new_email)}"/>'
        )

        self._post_soap(soap_body, action_label=f"đổi tên email {old_email} thành {new_email}")

    def delete_account(self, email: str):
        """Xóa vĩnh viễn account khỏi Zimbra (DeleteAccountRequest) -- KHÔNG thể khôi phục."""
        account_id = self._resolve_account_id(email, action_desc="xóa")

        soap_body = self._envelope(
            f'<DeleteAccountRequest xmlns="urn:zimbraAdmin" id="{escape(account_id)}"/>'
        )

        self._post_soap(soap_body, action_label=f"xóa email {email}")

    def get_backup_download_url(self, email: str) -> str:
        """
        URL tải backup mailbox dạng .tgz, dùng HTTP Basic Auth (không qua SOAP
        token) theo định dạng: https://<host>:7071/home/<email>/?fmt=tgz
        Việc gọi thực tế (stream file) do view xử lý để có thể trả thẳng cho
        client mà không load toàn bộ file vào RAM.
        """
        return f"https://{self.server.hostname}:7071/home/{email}/?fmt=tgz"