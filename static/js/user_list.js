/**
 * user_list.js - User Management with Tenant Logic
 *
 * LOGIC:
 * - Tenant Admin: Auto-assign their tenant (no dropdown)
 * - Superuser: Must explicitly select a tenant (required dropdown)
 */

document.addEventListener('DOMContentLoaded', () => {
    const userModalEl = document.getElementById('user-modal');
    const userModal = userModalEl ? new bootstrap.Modal(userModalEl) : null;

    // ========================================================================
    // 1️⃣ MODAL OPEN - Reset form when opening
    // ========================================================================
    const btnOpenAddUser = document.getElementById('btn-open-add-user');
    if (btnOpenAddUser) {
        btnOpenAddUser.addEventListener('click', () => {
            const form = document.getElementById('user-form');
            if (form) form.reset();

            // Reset tenant dropdown if superuser
            if (window.CURRENT_USER.isSuperuser) {
                const tenantSelect = document.getElementById('u_tenant_id');
                if (tenantSelect) {
                    tenantSelect.value = '';
                    tenantSelect.classList.remove('is-invalid');
                }
            }

            if (userModal) userModal.show();
        });
    }

    // ========================================================================
    // 2️⃣ TABLE - Change Status (Toggle checkbox)
    // ========================================================================
    const tableBody = document.getElementById('user-table-body');
    if (tableBody) {
        // Lắng nghe thay đổi của Công tắc Kích hoạt (Switch)
        tableBody.addEventListener('change', async (e) => {
            const checkbox = e.target.closest('.user-status-checkbox');
            if (!checkbox) return;

            const userId = checkbox.dataset.id;
            const isChecked = checkbox.checked;

            const formData = new FormData();
            formData.append('is_active', isChecked ? 'true' : 'false');

            const url = `/api/users/${userId}/status/`;
            const result = await fetchJSON(url, { method: 'POST', body: formData });

            if (result.ok) {
                showToast(
                    result.data.message || 'Cập nhật trạng thái tài khoản thành công.',
                    'success'
                );
            } else {
                showToast(
                    result.data.error || 'Lỗi khi cập nhật trạng thái.',
                    'danger'
                );
                // ✅ Khôi phục trạng thái UI nếu lỗi backend
                checkbox.checked = !isChecked;
            }
        });

        // Lắng nghe thay đổi của Hộp chọn Vai trò (Select box)
        tableBody.addEventListener('change', async (e) => {
            const selectRole = e.target.closest('.user-role-select');
            if (!selectRole) return;

            const userId = selectRole.dataset.id;
            const previousRole = selectRole.getAttribute('data-prev') || selectRole.value;
            const newRole = selectRole.value;

            const formData = new FormData();
            formData.append('role', newRole);

            const url = `/api/users/${userId}/role/`;
            const result = await fetchJSON(url, { method: 'POST', body: formData });

            if (result.ok) {
                showToast(
                    result.data.message || 'Thay đổi quyền hạn thành công.',
                    'success'
                );
                // ✅ Cập nhật bộ nhớ đệm vai trò
                selectRole.setAttribute('data-prev', newRole);
            } else {
                showToast(
                    result.data.error || 'Thao tác phân quyền thất bại.',
                    'danger'
                );
                // ✅ Trả giao diện về giá trị cũ
                selectRole.value = previousRole;
            }
        });

        // Tạo bộ nhớ đệm vai trò ban đầu cho tất cả select boxes
        tableBody.querySelectorAll('.user-role-select').forEach(select => {
            select.setAttribute('data-prev', select.value);
        });
    }

    // ========================================================================
    // 3️⃣ FORM SUBMIT - Create new user
    // ========================================================================
    const userForm = document.getElementById('user-form');
    if (userForm) {
        userForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            // ✅ Lấy dữ liệu từ form
            const email = document.getElementById('u_email').value.trim();
            const password = document.getElementById('u_pwd').value.trim();
            const fullName = document.getElementById('u_name').value.trim();

            // =========================================================
            // VALIDATION: Check required fields
            // =========================================================
            if (!email) {
                showToast('Email là bắt buộc', 'warning');
                return;
            }
            if (!password) {
                showToast('Mật khẩu là bắt buộc', 'warning');
                return;
            }

            // =========================================================
            // SUPERUSER LOGIC: Must select tenant
            // =========================================================
            let tenantId = null;
            if (window.CURRENT_USER.isSuperuser) {
                const tenantSelect = document.getElementById('u_tenant_id');
                if (!tenantSelect) {
                    showToast('❌ Lỗi: Không tìm thấy trường chọn tổ chức', 'danger');
                    return;
                }

                tenantId = tenantSelect.value.trim();

                // ✅ Validation: Superuser MUST choose tenant
                if (!tenantId) {
                    // Mark as invalid
                    tenantSelect.classList.add('is-invalid');
                    showToast(
                        '❌ Bạn phải chọn Tổ chức (Superuser bắt buộc)',
                        'danger'
                    );
                    return;
                }

                // ✅ Remove invalid mark if already filled
                tenantSelect.classList.remove('is-invalid');
            }

            // =========================================================
            // BUILD FormData
            // =========================================================
            const formData = new FormData();
            formData.append('email', email);
            formData.append('password', password);
            formData.append('full_name', fullName);

            // ✅ Superuser: append tenant_id
            // Tenant Admin: không append (backend sẽ auto-assign)
            if (window.CURRENT_USER.isSuperuser && tenantId) {
                formData.append('tenant_id', tenantId);
            }

            // =========================================================
            // SUBMIT
            // =========================================================
            const result = await postAndReload(
                window.USER_URLS.apiCreateStaff,
                formData,
                {
                    event: e,
                    successReload: true  // Reload page after success
                }
            );

            // ✅ Close modal if success
            if (result && result.ok && userModal) {
                userModal.hide();
            }
        });
    }
});