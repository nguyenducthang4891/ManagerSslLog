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
    const userTableBody = document.getElementById('user-table-body');
    if (userTableBody) {
        userTableBody.addEventListener('change', async (e) => {
            const checkbox = e.target.closest('.user-status-checkbox');
            if (!checkbox) return;

            const userId = checkbox.getAttribute('data-id');
            const isActive = checkbox.checked;

            const formData = new FormData();
            formData.append('is_active', isActive);

            const url = `/api/users/${userId}/status/`;
            await postAndReload(url, formData, { event: e, successReload: false });
        });

        // ========================================================================
        // 3️⃣ TABLE - Change Role (Dropdown select)
        // ========================================================================
        userTableBody.addEventListener('change', async (e) => {
            const select = e.target.closest('.user-role-select');
            if (!select) return;

            const userId = select.getAttribute('data-id');
            const newRole = select.value;

            const formData = new FormData();
            formData.append('role', newRole);

            const url = `/api/users/${userId}/role/`;
            await postAndReload(url, formData, { event: e, successReload: false });
        });
    }

    // ========================================================================
    // 4️⃣ SUBMIT FORM - Create Staff
    // ========================================================================
    const userForm = document.getElementById('user-form');
    if (userForm) {
        userForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const email = document.getElementById('u_email').value.trim();
            const password = document.getElementById('u_pwd').value;
            const fullName = document.getElementById('u_name').value.trim();
            const tenantSelect = document.getElementById('u_tenant_id');
            const tenantId = tenantSelect ? tenantSelect.value : null;

            // Validation nếu là Superuser
            if (window.CURRENT_USER.isSuperuser) {
                if (!tenantId) {
                    tenantSelect.classList.add('is-invalid');
                    showToast(
                        'Cảnh báo dữ liệu',
                        'Vui lòng chọn Tổ chức quản lý cho tài khoản nhân viên này!',
                        'danger'
                    );
                    return;
                }
                tenantSelect.classList.remove('is-invalid');
            }

            const formData = new FormData();
            formData.append('email', email);
            formData.append('password', password);
            formData.append('full_name', fullName);

            if (window.CURRENT_USER.isSuperuser && tenantId) {
                formData.append('tenant_id', tenantId);
            }

            const result = await postAndReload(
                window.USER_URLS.apiCreateStaff,
                formData,
                {
                    event: e,
                    successReload: true
                }
            );

            if (result && result.ok && userModal) {
                userModal.hide();
            }
        });
    }

    // ========================================================================
    // 5️⃣ MODAL RESET PASSWORD - Đặt lại mật khẩu (Đã sửa lỗi định vị)
    // ========================================================================
    const resetModalEl = document.getElementById('resetPasswordModal');
    const resetModal = resetModalEl ? new bootstrap.Modal(resetModalEl) : null;
    const resetForm = document.getElementById('resetPasswordForm');
    const errorAlert = document.getElementById('resetPasswordError');

    // Ủy quyền sự kiện (Event Delegation) lắng nghe nút click Reset trong bảng
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-reset-pwd');
        if (!btn) return;

        e.preventDefault();
        const userId = btn.getAttribute('data-user-id');
        const userEmail = btn.getAttribute('data-user-email');

        if (resetForm) resetForm.reset();
        if (errorAlert) {
            errorAlert.classList.add('d-none');
            errorAlert.textContent = '';
        }

        const inputId = document.getElementById('reset_user_id');
        const textEmail = document.getElementById('reset_user_email');
        if (inputId) inputId.value = userId;
        if (textEmail) textEmail.textContent = userEmail;

        if (resetModal) resetModal.show();
    });

    // Submit form Đổi mật khẩu
    if (resetForm) {
        resetForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const userId = document.getElementById('reset_user_id').value;
            const newPassword = document.getElementById('new_password').value;
            const confirmPassword = document.getElementById('confirm_password').value;
            const btnSubmit = document.getElementById('btnSubmitReset');

            if (newPassword !== confirmPassword) {
                if (errorAlert) {
                    errorAlert.textContent = 'Mật khẩu mới và xác nhận mật khẩu không trùng khớp.';
                    errorAlert.classList.remove('d-none');
                }
                return;
            }

            const formData = new FormData(resetForm);

            if (btnSubmit) {
                btnSubmit.disabled = true;
                btnSubmit.textContent = 'Đang xử lý...';
            }
            if (errorAlert) errorAlert.classList.add('d-none');

            // Lấy URL từ biến global window đã khai báo ngoài HTML
            const baseUrl = window.USER_URLS.apiResetUserPassword;
            const url = baseUrl.replace('0', userId);

            try {
                const result = await postAndReload(url, formData, {
                    event: e,
                    successReload: true
                });

                if (result && result.ok && resetModal) {
                    resetModal.hide();
                }
            } catch (err) {
                console.error('Reset password error:', err);
                if (errorAlert) {
                    errorAlert.textContent = 'Lỗi hệ thống không thể thực hiện.';
                    errorAlert.classList.remove('d-none');
                }
            } finally {
                if (btnSubmit) {
                    btnSubmit.disabled = false;
                    btnSubmit.textContent = 'Xác nhận cập nhật';
                }
            }
        });
    }
});