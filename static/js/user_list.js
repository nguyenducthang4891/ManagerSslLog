/**
 * user_list.js
 * JS riêng cho trang Quản lý Thành viên Tổ chức (templates/users/user_list.html).
 * Phụ thuộc: common.js.
 */

document.addEventListener('DOMContentLoaded', () => {

    // Sự kiện mở Modal thêm nhân viên mới
    const btnOpenAddUser = document.getElementById('btn-open-add-user');
    if (btnOpenAddUser) {
        btnOpenAddUser.addEventListener('click', () => {
            const form = document.getElementById('user-form');
            if (form) form.reset();
            toggleModal('user-modal', true);
        });
    }

    // Cơ chế Event Delegation lắng nghe thay đổi công tắc Trạng thái (Bật/Tắt kích hoạt)
    const tableBody = document.getElementById('user-table-body');
    if (tableBody) {
        tableBody.addEventListener('change', async (e) => {
            const checkbox = e.target.closest('.user-status-checkbox');
            if (!checkbox) return;

            const userId = checkbox.dataset.id;
            const isChecked = checkbox.checked;

            const formData = new FormData();
            formData.append('is_active', isChecked ? 'true' : 'false');

            const url = `/users/api/users/${userId}/status/`;
            const result = await fetchJSON(url, { method: 'POST', body: formData });

            if (result.ok) {
                showToast(result.data.message || 'Cập nhật trạng thái tài khoản thành công.', 'success');
            } else {
                showToast(result.data.error || 'Lỗi khi cập nhật trạng thái.', 'danger');
                checkbox.checked = !isChecked; // Hoàn tác giao diện nếu lỗi backend
            }
        });
    }

    // Luồng xử lý gửi Form đăng ký tài khoản mới
    const userForm = document.getElementById('user-form');
    if (userForm) {
        userForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData();
            formData.append('email', document.getElementById('u_email').value);
            formData.append('password', document.getElementById('u_pwd').value);
            formData.append('full_name', document.getElementById('u_name').value);

            // Gửi và reload trang thông qua core common.js để chặn click liên tiếp
            const result = await postAndReload(window.USER_URLS.apiCreateStaff, formData, { event: e });

            if (result && result.ok) {
                toggleModal('user-modal', false);
            }
        });
    }
});