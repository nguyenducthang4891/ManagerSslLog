document.addEventListener('DOMContentLoaded', () => {
    let isEditTenant = false;
    const tenantModalEl = document.getElementById('tenant-modal');
    const assignModalEl = document.getElementById('assign-modal');

    // Khởi tạo Bootstrap Modal instances
    const tenantModal = tenantModalEl ? new bootstrap.Modal(tenantModalEl) : null;
    const assignModal = assignModalEl ? new bootstrap.Modal(assignModalEl) : null;

    // Sự kiện mở modal tạo mới
    const btnOpenAdd = document.getElementById('btn-open-add-tenant');
    if (btnOpenAdd) {
        btnOpenAdd.addEventListener('click', () => {
            isEditTenant = false;
            document.getElementById('tenant-form').reset();
            document.getElementById('tenant-modal-title').textContent = "Khởi tạo Không gian Tenant";
            document.getElementById('code-container').classList.remove('d-none');
            document.getElementById('status-container').classList.add('d-none');
            if (tenantModal) tenantModal.show();
        });
    }

    // Cơ chế Event Delegation xử lý nút bấm trên bảng danh sách
    const tableBody = document.getElementById('tenant-table-body');
    if (tableBody) {
        tableBody.addEventListener('click', (e) => {
            const btnEdit = e.target.closest('.btn-edit');
            const btnAssign = e.target.closest('.btn-assign');

            if (btnEdit) {
                isEditTenant = true;
                const data = btnEdit.dataset;
                document.getElementById('t_id').value = data.id;
                document.getElementById('t_name').value = data.name;
                document.getElementById('t_active').value = data.active;

                document.getElementById('tenant-modal-title').textContent = "Cấu hình Thông tin Tổ chức";
                document.getElementById('code-container').classList.add('d-none');
                document.getElementById('status-container').classList.remove('d-none');
                if (tenantModal) tenantModal.show();
            }

            if (btnAssign) {
                const data = btnAssign.dataset;
                document.getElementById('assign_t_id').value = data.id;
                document.getElementById('assign-tenant-name').textContent = data.name;
                document.getElementById('assign_user_id').value = "";
                if (assignModal) assignModal.show();
            }
        });
    }

    // Gửi dữ liệu form Thêm/Sửa Tenant
    const tenantForm = document.getElementById('tenant-form');
    if (tenantForm) {
        tenantForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append('name', document.getElementById('t_name').value);

            let url = window.TENANT_URLS.apiAddTenant;
            if (isEditTenant) {
                const id = document.getElementById('t_id').value;
                url = `/users/api/tenants/${id}/edit/`;
                formData.append('is_active', document.getElementById('t_active').value);
            } else {
                formData.append('code', document.getElementById('t_code').value);
            }

            const result = await postAndReload(url, formData, { event: e });
            if (result && result.ok && tenantModal) {
                tenantModal.hide();
            }
        });
    }

    // Gửi dữ liệu form chỉ định Admin quản trị Tenant
    const assignForm = document.getElementById('assign-form');
    if (assignForm) {
        assignForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append('tenant_id', document.getElementById('assign_t_id').value);
            formData.append('user_id', document.getElementById('assign_user_id').value);

            const result = await postAndReload(window.TENANT_URLS.apiAssignAdmin, formData, { event: e });
            if (result && result.ok && assignModal) {
                assignModal.hide();
            }
        });
    }
});