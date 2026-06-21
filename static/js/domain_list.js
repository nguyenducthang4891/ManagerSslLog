/**
 * domain_list.js
 * JS riêng cho trang Quản lý Tên miền (templates/networks/domain_list.html).
 * Phụ thuộc: common.js (phải load trước file này trong base.html).
 */

document.addEventListener('DOMContentLoaded', () => {
    let isDomEditMode = false;

    // --- KHỞI TẠO SỰ KIỆN GIAO DIỆN ---

    // Bấm nút Mở Modal Khai báo Domain mới
    const btnOpenAdd = document.getElementById('btn-open-add-modal');
    if (btnOpenAdd) {
        btnOpenAdd.addEventListener('click', () => {
            isDomEditMode = false;
            document.getElementById('domain-form').reset();
            document.getElementById('dom-modal-title').textContent = "Khai báo Domain tổ chức mới";
            document.getElementById('dom_name').disabled = false;
            toggleModal('domain-modal', true);
        });
    }

    // Bấm nút Sửa / Đổi cụm Server trên từng hàng
    document.querySelectorAll('.btn-edit-domain-trigger').forEach(btn => {
        btn.addEventListener('click', (e) => {
            isDomEditMode = true;
            const target = e.target.closest('.btn-edit-domain-trigger');

            document.getElementById('dom-modal-title').textContent = "Điều chuyển cụm Server gán Domain";
            document.getElementById('dom_id').value = target.dataset.id;
            document.getElementById('dom_name').value = target.dataset.name;
            document.getElementById('dom_name').disabled = true;
            document.getElementById('dom_server').value = target.dataset.server;

            toggleModal('domain-modal', true);
        });
    });

    // Bấm nút Điều phối Tenant (Chỉ chạy khi là Superuser - phần tử tồn tại)
    document.querySelectorAll('.btn-assign-tenant-trigger').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const target = e.target.closest('.btn-assign-tenant-trigger');
            const currentTenantId = target.dataset.tenant;

            document.getElementById('assign_dom_id').value = target.dataset.id;
            document.getElementById('assign-dom-name').textContent = target.dataset.name;
            document.getElementById('assign_tenant_id').value = currentTenantId;

            const btnDetach = document.getElementById('btn-quick-detach');
            if (btnDetach) {
                btnDetach.classList.toggle('d-none', !currentTenantId);
            }

            toggleModal('assign-tenant-modal', true);
        });
    });

    // Bấm nút Xóa trên từng hàng
    document.querySelectorAll('.btn-delete-domain-trigger').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const target = e.target.closest('.btn-delete-domain-trigger');
            const id = target.dataset.id;
            const name = target.dataset.name;

            // Dùng trực tiếp helper, truyền e để khóa cứng nút xóa lại trong lúc chờ
            postAndReload(`/networks/api/domains/${id}/delete/`, null, {
                confirmMessage: `Xác nhận xóa hoàn toàn cấu hình domain [ ${name} ] khỏi hệ thống? Dữ liệu trên server Zimbra thật sẽ không bị ảnh hưởng.`,
                event: e
            });
        });
    });


    // --- XỬ LÝ SUBMIT CÁC FORM (ỨNG DỤNG MÔ HÌNH TOÀN DIỆN TỪ COMMON.JS) ---

    // Submit Form Thêm / Sửa Domain
    const domainForm = document.getElementById('domain-form');
    if (domainForm) {
        domainForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData();
            formData.append('server_id', document.getElementById('dom_server').value);
            if (!isDomEditMode) {
                formData.append('name', document.getElementById('dom_name').value);
            }

            const url = isDomEditMode
                ? `/networks/api/domains/${document.getElementById('dom_id').value}/edit/`
                : window.DOMAIN_URLS.apiAddDomain;

            // Tối ưu: Dùng postAndReload, truyền e để tự động khóa nút Submit, tự bắt lỗi
            const result = await postAndReload(url, formData, { event: e });
            if (result && result.ok) {
                toggleModal('domain-modal', false);
            }
        });
    }

    // Submit Form Điều phối Tenant (Superuser)
    const assignTenantForm = document.getElementById('assign-tenant-form');
    if (assignTenantForm) {
        assignTenantForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData();
            formData.append('domain_id', document.getElementById('assign_dom_id').value);
            formData.append('tenant_id', document.getElementById('assign_tenant_id').value);

            // Khóa nút submit bằng event e, tự hiện thông báo thành công/thất bại
            const result = await postAndReload(window.DOMAIN_URLS.apiAssignTenant, formData, { event: e });
            if (result && result.ok) {
                toggleModal('assign-tenant-modal', false);
            }
        });
    }

    // Bấm nút Gỡ bỏ Tenant khẩn cấp ngay tại chỗ (Superuser)
    const btnQuickDetach = document.getElementById('btn-quick-detach');
    if (btnQuickDetach) {
        btnQuickDetach.addEventListener('click', async (e) => {
            if (!confirm("Bạn có chắc chắn muốn gỡ Domain này khỏi Tổ chức hiện tại, đưa về dạng dùng chung (Tự do)?")) return;

            const formData = new FormData();
            formData.append('domain_id', document.getElementById('assign_dom_id').value);
            formData.append('tenant_id', '');

            // Khóa liên kết text click bằng event e chống click spam phá dữ liệu
            const result = await postAndReload(window.DOMAIN_URLS.apiAssignTenant, formData, { event: e });
            if (result && result.ok) {
                toggleModal('assign-tenant-modal', false);
            }
        });
    }
});