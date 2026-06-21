/**
 * tenant_list.js
 * JS riêng cho trang Quản lý Tổ chức (templates/tenants/tenant_list.html).
 * Phụ thuộc: common.js (phải load trước file này).
 */

document.addEventListener('DOMContentLoaded', () => {
    let isEditTenant = false;

    // --- KHỞI TẠO SỰ KIỆN GIAO DIỆN CHÍNH ---

    // Sự kiện mở modal khởi tạo Tenant mới
    const btnOpenAdd = document.getElementById('btn-open-add-tenant');
    if (btnOpenAdd) {
        btnOpenAdd.addEventListener('click', () => {
            isEditTenant = false;
            document.getElementById('tenant-form').reset();
            document.getElementById('tenant-modal-title').textContent = "Khởi tạo Không gian Tenant";
            document.getElementById('code-container').classList.remove('d-none');
            document.getElementById('status-container').classList.add('d-none');
            toggleModal('tenant-modal', true);
        });
    }

    // CƠ CHẾ ỦY NHIỆM SỰ KIỆN (Event Delegation) CHO BẢNG DANH SÁCH TENANT
    // Lắng nghe tập trung sự kiện từ thẻ cha thay vì gán hàng trăm hàm inline vào từng ô cấu hình
    const tableBody = document.getElementById('tenant-table-body');
    if (tableBody) {
        tableBody.addEventListener('click', (e) => {
            // Trường hợp nhấn nút Gán Quyền Admin
            const assignBtn = e.target.closest('.btn-assign-trigger');
            if (assignBtn) {
                document.getElementById('assign_t_id').value = assignBtn.dataset.id;
                document.getElementById('assign-tenant-name').textContent = assignBtn.dataset.name;
                document.getElementById('assign_user_id').value = ''; // Reset select
                toggleModal('assign-modal', true);
                return;
            }

            // Trường hợp nhấn nút Chỉnh sửa thông tin
            const editBtn = e.target.closest('.btn-edit-trigger');
            if (editBtn) {
                isEditTenant = true;
                document.getElementById('tenant-modal-title').textContent = "Cập nhật thông tin Tenant";
                document.getElementById('t_id').value = editBtn.dataset.id;
                document.getElementById('t_name').value = editBtn.dataset.name;
                document.getElementById('t_active').value = editBtn.dataset.active;
                document.getElementById('code-container').classList.add('d-none'); // Khóa mã Code định danh
                document.getElementById('status-container').classList.remove('d-none');
                toggleModal('tenant-modal', true);
                return;
            }

            // Trường hợp nhấn nút Xóa
            const deleteBtn = e.target.closest('.btn-delete-trigger');
            if (deleteBtn) {
                const tenantId = deleteBtn.dataset.id;
                postAndReload(
                    `/users/api/tenants/${tenantId}/delete/`,
                    null,
                    { confirmMessage: "Xác nhận xóa hoàn toàn Tenant này khỏi hệ thống?" }
                );
            }
        });
    }

    // --- XỬ LÝ SUBMIT CÁC BIỂU MẪU (FORMS) ---

    // Submit form thêm mới hoặc chỉnh sửa thông tin Tenant
    const tenantForm = document.getElementById('tenant-form');
    if (tenantForm) {
        tenantForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append('name', document.getElementById('t_name').value);

            let url = window.TENANT_URLS.apiAddTenant;
            if (isEditTenant) {
                url = `/users/api/tenants/${document.getElementById('t_id').value}/edit/`;
                formData.append('is_active', document.getElementById('t_active').value);
            } else {
                formData.append('code', document.getElementById('t_code').value);
            }

            // Thực thi qua postAndReload để quản lý trạng thái nút bấm và tự nạp lại trang
            const result = await postAndReload(url, formData, { event: e });
            if (result && result.ok) {
                toggleModal('tenant-modal', false);
            }
        });
    }

    // Submit form chỉ định quyền Admin quản lý Tenant
    const assignForm = document.getElementById('assign-form');
    if (assignForm) {
        assignForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append('tenant_id', document.getElementById('assign_t_id').value);
            formData.append('user_id', document.getElementById('assign_user_id').value);

            const result = await postAndReload(window.TENANT_URLS.apiAssignAdmin, formData, { event: e });
            if (result && result.ok) {
                toggleModal('assign-modal', false);
            }
        });
    }
});