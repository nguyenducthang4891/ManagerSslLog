/**
 * cert_detail.js
 * Xử lý nghiệp vụ Polling Log realtime và cập nhật trạng thái Deploy Chứng chỉ.
 * Phụ thuộc: common.js.
 */

let logInterval = null;

document.addEventListener('DOMContentLoaded', () => {

    // Nạp lịch sử deploy ngay khi vừa mở trang
    reloadDeployHistory();

    // Sự kiện nút "Triển khai ngay"
    const btnDeploy = document.getElementById('btn-deploy');
    if (btnDeploy) {
        btnDeploy.addEventListener('click', startDeploy);
    }

    // Sự kiện nút "Làm mới bảng" lịch sử
    const btnRefresh = document.getElementById('btn-refresh-history');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', (e) => {
            e.preventDefault();
            reloadDeployHistory();
        });
    }

    // Cơ chế Event Delegation cho bảng lịch sử để lắng nghe sự kiện bấm nút xem Log cũ
    const historyBody = document.getElementById('deploy-history-body');
    if (historyBody) {
        historyBody.addEventListener('click', (e) => {
            const viewBtn = e.target.closest('.btn-view-log-trigger');
            if (viewBtn) {
                viewHistoryLog(viewBtn.dataset.historyId);
            }
        });
    }

    // Kiểm tra nghiệp vụ: Nếu Cert đang ở trạng thái deploy dở dang từ trước, tự động nối tiếp phiên quét log
    if (window.CERT_INITIAL_STATUS === 'deploying') {
        document.getElementById('log-spinner').classList.remove('d-none');
        lockDeployButton(true);
        logInterval = setInterval(fetchLogs, 2000);
    }
});

/**
 * Hàm kích hoạt tiến trình Automation Deploy ngầm
 */
async function startDeploy() {
    if (!confirm("Xác nhận kích hoạt Ansible/Script triển khai chứng chỉ này lên máy chủ Zimbra từ xa?")) return;

    lockDeployButton(true);
    document.getElementById('log-spinner').classList.remove('d-none');

    const result = await fetchJSON(window.CERT_DETAIL_URLS.apiTriggerDeploy, { method: 'POST' });

    if (result.ok) {
        showToast(result.data.message || 'Đã kích hoạt tiến trình triển khai thành công!', 'success');
        logInterval = setInterval(fetchLogs, 2000); // Bắt đầu vòng lặp polling 2 giây/lần
    } else {
        showToast(result.data.error || 'Không thể kích hoạt deploy.', 'danger');
        lockDeployButton(false);
        document.getElementById('log-spinner').classList.add('d-none');
    }
}

/**
 * Hàm Polling kéo dữ liệu log realtime từ backend
 */
async function fetchLogs() {
    const result = await fetchJSON(window.CERT_DETAIL_URLS.apiGetRealtimeLog, { method: 'GET' });
    if (!result.ok) return;

    const data = result.data;
    const consoleBox = document.getElementById('terminal-console');
    const statusBox = document.getElementById('cert-status');

    // Cập nhật nội dung text và tự động cuộn màn hình console xuống cuối dòng log
    consoleBox.textContent = data.deploy_log;
    consoleBox.scrollTop = consoleBox.scrollHeight;

    statusBox.textContent = data.status_display || data.status;
    updateStatusBadgeColor(statusBox, data.status);

    // Kịch bản kết thúc: Script chạy xong xuôi (Thành công hoặc Thất bại)
    if (data.status === 'deployed' || data.status === 'failed') {
        clearInterval(logInterval);
        document.getElementById('log-spinner').classList.add('d-none');
        lockDeployButton(false);
        reloadDeployHistory(); // Tự động làm mới danh sách lịch sử
        showToast(data.status === 'deployed' ? 'Triển khai chứng chỉ thành công!' : 'Tiến trình triển khai thất bại.', data.status === 'deployed' ? 'success' : 'danger');
    }
}

/**
 * Cập nhật màu sắc động cho Badge trạng thái theo chuẩn Bootstrap 5 màu dịu nhẹ (-subtle)
 */
function updateStatusBadgeColor(el, status) {
    el.className = 'fw-semibold text-uppercase px-2 py-1 rounded small ' + ({
        deployed: 'bg-success-subtle text-success-emphasis border border-success-subtle',
        deploying: 'bg-warning-subtle text-warning-emphasis border border-warning-subtle',
        failed: 'bg-danger-subtle text-danger-emphasis border border-danger-subtle',
    }[status] || 'bg-secondary-subtle text-secondary-emphasis border border-secondary-subtle');
}

/**
 * Nạp lại danh sách lịch sử deploy bằng cơ chế AJAX mượt mà
 */
async function reloadDeployHistory() {
    const tbody = document.getElementById('deploy-history-body');
    const result = await fetchJSON(window.CERT_DETAIL_URLS.apiGetDeployHistory, { method: 'GET' });

    if (!result.ok) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-danger py-3">Lỗi khi tải dữ liệu lịch sử.</td></tr>';
        return;
    }

    const rows = result.data.history || [];
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">Chưa có lần deploy nào được ghi nhận.</td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(h => {
        const duration = h.duration_seconds !== null ? `${Math.round(h.duration_seconds)}s` : '--';
        const badge = h.status === 'success'
            ? '<span class="badge rounded-pill text-bg-success-subtle text-success px-2.5 border border-success-subtle">Thành công</span>'
            : '<span class="badge rounded-pill text-bg-danger-subtle text-danger px-2.5 border border-danger-subtle">Thất bại</span>';

        return `
            <tr>
                <td class="ps-3 font-monospace">${h.started_at}</td>
                <td class="text-muted">${h.triggered_by}</td>
                <td class="font-monospace">${duration}</td>
                <td>${badge}</td>
                <td class="pe-3 text-end">
                    <button class="btn btn-sm btn-outline-primary btn-view-log-trigger" data-history-id="${h.id}" title="Xem chi tiết log">
                        <i class="bi bi-eye"></i> Log
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

/**
 * Mở modal kết hợp AJAX lấy snapshot log cũ trong quá khứ
 */
async function viewHistoryLog(historyId) {
    const url = window.CERT_DETAIL_URLS.apiGetDeployHistoryDetailTemplate.replace('999999999', historyId);
    const contentBox = document.getElementById('history-log-content');

    contentBox.textContent = "Đang tải dữ liệu log từ cơ sở dữ liệu...";
    toggleModal('history-log-modal', true);

    const result = await fetchJSON(url, { method: 'GET' });
    if (result.ok) {
        contentBox.textContent = result.data.log_snapshot || '(Lần deploy này không ghi nhận cấu hình log lưu lại.)';
    } else {
        contentBox.textContent = result.data.error || 'Lỗi hệ thống: Không thể kết nối để lấy log.';
    }
}

/**
 * Hàm phụ trợ khóa hoặc mở khóa nút bấm triển khai
 */
function lockDeployButton(shouldLock) {
    const btn = document.getElementById('btn-deploy');
    if (!btn) return;
    btn.disabled = shouldLock;
    if (shouldLock) {
        btn.classList.add('disabled');
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Đang deploy...';
    } else {
        btn.classList.remove('disabled');
        btn.innerHTML = '<i class="bi bi-rocket-takeoff me-1"></i>Triển khai ngay lên Zimbra';
    }
}