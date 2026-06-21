/**
 * server_list.js
 * JS riêng cho trang Danh sách Cụm máy chủ Zimbra (templates/networks/server_list.html).
 * Phụ thuộc: common.js (phải load trước file này trong base.html).
 */

document.addEventListener('DOMContentLoaded', () => {
    let isEditMode = false;

    // --- KHỞI TẠO SỰ KIỆN GIAO DIỆN ---

    // Sự kiện mở Modal Thêm Server mới
    const btnOpenAdd = document.getElementById('btn-open-add-modal');
    if (btnOpenAdd) {
        btnOpenAdd.addEventListener('click', () => {
            isEditMode = false;
            document.getElementById('server-form').reset();
            document.getElementById('modal-title').textContent = "Khai báo Server Hạ tầng mới";
            document.getElementById('srv_pwd').placeholder = "Nếu dùng key thì bỏ trống";
            document.getElementById('srv_admin_pwd').required = true;
            document.getElementById('srv_admin_pwd').placeholder = "";
            toggleModal('server-modal', true);
        });
    }

    // Sự kiện mở Modal Sửa cấu hình Server trên từng dòng
    document.querySelectorAll('.btn-edit-server-trigger').forEach(btn => {
        btn.addEventListener('click', (e) => {
            isEditMode = true;
            const target = e.target.closest('.btn-edit-server-trigger');

            document.getElementById('modal-title').textContent = "Cập nhật cấu hình Server";
            document.getElementById('srv_id').value = target.dataset.id;
            document.getElementById('srv_name').value = target.dataset.name;
            document.getElementById('srv_host').value = target.dataset.host;
            document.getElementById('srv_port').value = target.dataset.port;
            document.getElementById('srv_user').value = target.dataset.user;

            // Xóa trắng mật khẩu để tăng tính an toàn và đổi trạng thái placeholder
            document.getElementById('srv_pwd').value = '';
            document.getElementById('srv_pwd').placeholder = "Bỏ trống nếu không đổi mật khẩu";

            document.getElementById('srv_admin_email').value = target.dataset.email;
            document.getElementById('srv_admin_pwd').value = '';
            document.getElementById('srv_admin_pwd').placeholder = "Bỏ trống nếu không đổi mật khẩu";
            document.getElementById('srv_admin_pwd').required = false;

            toggleModal('server-modal', true);
        });
    });

    // Sự kiện click nút Check SSH kết nối hạ tầng
    document.querySelectorAll('.btn-check-ssh-trigger').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const target = e.target.closest('.btn-check-ssh-trigger');
            checkSshConnection(target.dataset.id);
        });
    });

    // Sự kiện click nút Check SOAP kết nối ứng dụng Zimbra API
    document.querySelectorAll('.btn-check-soap-trigger').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const target = e.target.closest('.btn-check-soap-trigger');
            checkSoapConnection(target.dataset.id);
        });
    });


    // --- XỬ LÝ GỬI DỮ LIỆU VÀ KIỂM TRA TRẠNG THÁI ---

    // Submit Form Thêm / Cập nhật Server
    const serverForm = document.getElementById('server-form');
    if (serverForm) {
        serverForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData();
            formData.append('name', document.getElementById('srv_name').value);
            formData.append('hostname', document.getElementById('srv_host').value);
            formData.append('port', document.getElementById('srv_port').value);
            formData.append('username', document.getElementById('srv_user').value);
            formData.append('password', document.getElementById('srv_pwd').value);
            formData.append('srv_admin_email', document.getElementById('srv_admin_email').value);
            formData.append('zimbra_admin_password', document.getElementById('srv_admin_pwd').value);

            const url = isEditMode
                ? `/networks/api/servers/${document.getElementById('srv_id').value}/edit/`
                : window.SERVER_URLS.apiAddServer;

            // Chuyển dịch toàn bộ sang postAndReload để tận dụng hệ thống khóa nút Submit tự động thông qua e
            const result = await postAndReload(url, formData, { event: e });
            if (result && result.ok) {
                toggleModal('server-modal', false);
            }
        });
    }

    // Hàm gọi API kiểm tra SSH Connection realtime
    async function checkSshConnection(serverId) {
        const btn = document.getElementById(`btn-ssh-${serverId}`);
        const text = document.getElementById(`text-ssh-${serverId}`);

        text.textContent = "Connecting...";
        btn.disabled = true;
        setButtonVariant(btn, 'warning');

        const result = await fetchJSON(`/networks/api/servers/${serverId}/test-connection/`, { method: 'POST' });

        if (result.ok) {
            showToast("🟢 SSH OK: " + (result.data.message || 'Kết nối thành công'), 'success');
            text.textContent = "SSH OK";
            setButtonVariant(btn, 'success');
        } else {
            showToast("🔴 SSH LỖI: " + (result.data.error || 'Không rõ nguyên nhân'), 'danger');
            text.textContent = "SSH Error";
            setButtonVariant(btn, 'danger');
        }
        btn.disabled = false;
    }

    // Hàm gọi API kiểm tra Zimbra SOAP API Connection realtime
    async function checkSoapConnection(serverId) {
        const btn = document.getElementById(`btn-soap-${serverId}`);
        const text = document.getElementById(`text-soap-${serverId}`);

        text.textContent = "Checking...";
        btn.disabled = true;
        setButtonVariant(btn, 'warning');

        const result = await fetchJSON(`/networks/api/servers/${serverId}/test-soap/`, { method: 'POST' });

        if (result.ok) {
            showToast("🟢 SOAP API OK: " + (result.data.message || 'Xác thực API thành công'), 'success');
            text.textContent = "SOAP OK";
            setButtonVariant(btn, 'success');
        } else {
            showToast("🔴 SOAP API LỖI: " + (result.data.error || 'Không rõ nguyên nhân'), 'danger');
            text.textContent = "SOAP Error";
            setButtonVariant(btn, 'danger');
        }
        btn.disabled = false;
    }

    // Helper đổi màu trạng thái nút bấm
    function setButtonVariant(btn, variant) {
        btn.className = `btn btn-${variant} btn-sm`;
    }
});