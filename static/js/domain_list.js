document.addEventListener('DOMContentLoaded', function () {
    // 1. Khởi tạo các phần tử Modal từ Bootstrap
    const domainModalEl = document.getElementById('domain-modal');
    const domainModal = new bootstrap.Modal(domainModalEl);

    const assignTenantModalEl = document.getElementById('assign-tenant-modal');
    const assignTenantModal = assignTenantModalEl ? new bootstrap.Modal(assignTenantModalEl) : null;

    // 2. Định nghĩa các thành phần biểu mẫu chính (DOM Elements)
    const domainForm = document.getElementById('domain-form');
    const domIdInput = document.getElementById('dom_id');
    const domNameInput = document.getElementById('dom_name');
    const domServerSelect = document.getElementById('dom_server');
    const domModalTitle = document.getElementById('dom-modal-title');
    const zimbraProvisionContainer = document.getElementById('zimbra-provision-container');
    const domCreateOnZimbraCheckbox = document.getElementById('dom_create_on_zimbra');

    // FIX: Khai báo đầy đủ phần tử form để tránh lỗi "not defined"
    const assignTenantForm = document.getElementById('assign-tenant-form');

    // 3. REGEX Kiểm tra định dạng Tên miền phía Client
    const domainRegex = /^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6}$/;

    // Lắng nghe sự kiện người dùng gõ vào ô domain để xóa trạng thái cảnh báo lỗi đỏ
    domNameInput.addEventListener('input', function() {
        domNameInput.classList.remove('is-invalid');
    });

    // Sự kiện mở Modal Thêm mới tên miền
    document.getElementById('btn-open-add-modal').addEventListener('click', function () {
        domIdInput.value = '';
        domNameInput.value = '';
        domNameInput.disabled = false;
        domNameInput.classList.remove('is-invalid');
        domServerSelect.value = '';
        domModalTitle.innerText = 'Khai báo Domain tổ chức';

        if (zimbraProvisionContainer) {
            zimbraProvisionContainer.style.display = 'block';
            domCreateOnZimbraCheckbox.checked = true; // Mặc định bật
        }
        domainModal.show();
    });

    // Ủy quyền sự kiện Click trên bảng danh sách domain (Sửa/Đổi Server, Gán Tenant, Xóa)
    document.addEventListener('click', function (e) {
        // Nhánh xử lý: Đổi Server / Sửa thông tin
        const editBtn = e.target.closest('.btn-edit-domain-trigger');
        if (editBtn) {
            domIdInput.value = editBtn.dataset.id;
            domNameInput.value = editBtn.dataset.name;
            domNameInput.disabled = true; // Khóa tên miền cũ, tránh chỉnh sửa làm lệch pha logic
            domNameInput.classList.remove('is-invalid');
            domServerSelect.value = editBtn.dataset.server;
            domModalTitle.innerText = 'Điều phối lại hạ tầng Server cho Domain';

            if (zimbraProvisionContainer) {
                zimbraProvisionContainer.style.display = 'none'; // Ẩn checkbox khi đổi server
            }
            domainModal.show();
            return;
        }

        // Nhánh xử lý: Điều phối Tenant (Chỉ hoạt động đối với Superadmin)
        const assignBtn = e.target.closest('.btn-assign-tenant-trigger');
        if (assignBtn && assignTenantModal) {
            document.getElementById('assign_dom_id').value = assignBtn.dataset.id;
            document.getElementById('assign-dom-name').innerText = assignBtn.dataset.name;
            const tenantSelect = document.getElementById('assign_tenant_id');
            if (tenantSelect) {
                tenantSelect.value = assignBtn.dataset.tenant || '';
            }
            assignTenantModal.show();
            return;
        }

        // Nhánh xử lý: Yêu cầu xóa tên miền
        const deleteBtn = e.target.closest('.btn-delete-domain-trigger');
        if (deleteBtn) {
            const domainId = deleteBtn.dataset.id;
            const domainName = deleteBtn.dataset.name;
            if (confirm(`Bạn có chắc chắn muốn xóa tên miền "${domainName}" khỏi hệ thống luận lý?`)) {
                executeDeleteDomain(domainId);
            }
        }
    });

    // Thao tác gửi dữ liệu Submit: Thêm mới hoặc Sửa Server phụ trách
    domainForm.addEventListener('submit', function (e) {
        e.preventDefault();

        const domId = domIdInput.value;
        const domainValue = domNameInput.value.trim().toLowerCase();

        // Thực thi kiểm tra định dạng dữ liệu đầu vào (Validate Frontend)
        if (!domainRegex.test(domainValue)) {
            domNameInput.classList.add('is-invalid');
            const feedback = document.getElementById('dom_name_feedback');
            if (feedback) {
                feedback.innerText = "Định dạng domain không hợp lệ (Ví dụ hợp lệ: site.com, sub.domain.vn)";
            }
            domNameInput.focus();
            return;
        }

        // Cấu hình URL chuẩn xác theo cụm tiền tố định tuyến hệ thống /networks/ của bạn
        let url = window.DOMAIN_URLS.apiAddDomain;
        if (domId) {
            url = `/networks/api/domains/${domId}/edit/`;
        }

        const formData = new FormData();
        formData.append('name', domainValue);
        formData.append('server_id', domServerSelect.value);

        // Thu thập trạng thái nút Checkbox nếu container đang hiển thị (chế độ Thêm mới)
        if (zimbraProvisionContainer && zimbraProvisionContainer.style.display !== 'none') {
            if (domCreateOnZimbraCheckbox.checked) {
                formData.append('create_on_zimbra', 'true');
            }
        }

        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        fetch(url, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': csrfToken
            }
        })
        .then(response => response.json().then(data => ({ status: response.status, body: data })))
        .then(res => {
            if (res.status === 200 || res.status === 201) {
                alert(res.body.message || 'Thao tác dữ liệu thành công.');
                location.reload();
            } else {
                alert(res.body.error || 'Đã xảy ra lỗi hệ thống.');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Mất kết nối mạng, vui lòng kiểm tra lại hạ tầng.');
        });
    });

    // FIX CHỮA LỖI: Chỉ gán sự kiện lắng nghe submit nếu phần tử form thực sự tồn tại trên DOM (Dành cho Superadmin)
    if (assignTenantForm) {
        assignTenantForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const formData = new FormData();
            formData.append('domain_id', document.getElementById('assign_dom_id').value);
            formData.append('tenant_id', document.getElementById('assign_tenant_id').value);

            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

            fetch(window.DOMAIN_URLS.apiAssignTenant, {
                method: 'POST',
                body: formData,
                headers: { 'X-CSRFToken': csrfToken }
            })
            .then(response => response.json().then(data => ({ status: response.status, body: data })))
            .then(res => {
                if (res.status === 200) {
                    alert(res.body.message);
                    location.reload();
                } else {
                    alert(res.body.error || 'Lỗi xử lý bàn giao quyền sở hữu.');
                }
            })
            .catch(err => alert('Lỗi kết nối API điều phối.'));
        });

        // Nút gỡ bỏ nhanh Tenant liên kết (Trả domain về trạng thái tự do)
        const btnQuickDetach = document.getElementById('btn-quick-detach');
        if (btnQuickDetach) {
            btnQuickDetach.addEventListener('click', function() {
                const tenantSelect = document.getElementById('assign_tenant_id');
                if (tenantSelect) {
                    tenantSelect.value = '';
                    assignTenantForm.requestSubmit(); // Gọi lệnh tự kích hoạt submit form
                }
            });
        }
    }

    // Hàm gọi API thực hiện Xóa dữ liệu Domain (Đã đồng bộ đường dẫn theo prefix /networks/)
    function executeDeleteDomain(domainId) {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        fetch(`/networks/api/domains/${domainId}/delete/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        })
        .then(response => response.json().then(data => ({ status: response.status, body: data })))
        .then(res => {
            if (res.status === 200) {
                alert(res.body.message || 'Đã xóa tên miền thành công khỏi hệ thống quản lý.');
                location.reload();
            } else {
                alert(res.body.error || 'Yêu cầu xóa bị từ chối từ hệ thống.');
            }
        })
        .catch(err => alert('Lỗi kết nối mạng khi thực hiện lệnh xóa.'));
    }
});