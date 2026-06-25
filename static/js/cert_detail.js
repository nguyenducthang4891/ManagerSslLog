/**
 * cert_detail.js
 * Xử lý nghiệp vụ Polling Log realtime, cập nhật, xóa và kiểm tra cài đặt SSL trực tế.
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

    const btnCancelUpdate = document.querySelector('#modalUpdateCert [data-bs-dismiss="modal"]');
    if (btnCancelUpdate) {
        btnCancelUpdate.addEventListener('click', () => {
            // Chủ động gọi hàm tắt modal có sẵn từ cấu trúc hệ thống (common.js)
            toggleModal('modalUpdateCert', false);
        });
    }

    // --- MỚI: XỬ LÝ SUBMIT CẬP NHẬT CHỨNG CHỈ (modalUpdateCert) ---
    const updateForm = document.getElementById('update-ssl-form');
    if (updateForm) {
        updateForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const btnSubmit = document.getElementById('btn-submit-update');
            const originalBtnHtml = btnSubmit.innerHTML;

            // Khóa nút tránh double-submit
            btnSubmit.disabled = true;
            btnSubmit.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Đang xử lý...';

            const formData = new FormData();
            formData.append('name', document.getElementById('edit_ssl_name').value);
            formData.append('domain_id', document.getElementById('edit_ssl_domain').value);

            // Chỉ đính kèm tệp tin nếu người dùng thực sự chọn file mới
            const serverFile = document.getElementById('edit_f_server').files[0];
            if (serverFile) formData.append('server_cert', serverFile);

            const keyFile = document.getElementById('edit_f_key').files[0];
            if (keyFile) formData.append('private_key', keyFile);

            const interFile = document.getElementById('edit_f_inter').files[0];
            if (interFile) formData.append('inter_cert', interFile);

            const rootFile = document.getElementById('edit_f_root').files[0];
            if (rootFile) formData.append('root_cert', rootFile);

            try {
                // Sử dụng URL từ cấu hình Endpoint routing được khai báo tập trung trong template
                const url = window.CERT_DETAIL_URLS.apiUpdateCert;

                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                    },
                    body: formData
                });

                const result = await response.json();

                if (response.ok) {
                    alert(result.message || 'Cập nhật thông tin chứng chỉ thành công!');
                    // Tự động reload lại trang để cập nhật thông tin hiển thị mới nhất
                    window.location.reload();
                } else {
                    alert('Lỗi: ' + (result.error || 'Không thể cập nhật chứng chỉ.'));
                }
            } catch (err) {
                console.error(err);
                alert('Có lỗi hệ thống xảy ra khi kết nối tới máy chủ.');
            } finally {
                // Trả lại trạng thái nút bấm ban đầu
                btnSubmit.disabled = false;
                btnSubmit.innerHTML = originalBtnHtml;
            }
        });
    }

    // Kiểm tra nghiệp vụ: Nếu Cert đang ở trạng thái deploy dở dang từ trước, tự động nối tiếp phiên quét log
    // Dùng biến server-side window.CERT_INITIAL_STATUS (chính xác 100%, không phụ thuộc
    // text hiển thị trên badge -- vốn có thể bị đổi nhãn tiếng Việt sau này).
    const initialStatus = (window.CERT_INITIAL_STATUS || '').toLowerCase();
    if (initialStatus === 'deploying') {
        lockDeployButton(true);
        startPollingLog();
    }
});

/**
 * MỚI: Kiểm tra kết nối cài đặt thực tế của SSL (Check Live)
 */
function checkSslLive(certId) {
    const resultDiv = document.getElementById('check-live-result');
    if (!resultDiv) return;

    resultDiv.className = "mt-3 alert alert-info";
    resultDiv.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Đang kết nối SSL qua cổng 443 của Domain...';
    resultDiv.classList.remove('d-none');

    fetch(`/ssl/api/certificates/${certId}/check-live/`)
        .then(res => res.json())
        .then(data => {
            if (data.status === 'ok') {
                resultDiv.className = "mt-3 alert alert-success d-flex align-items-start";
                resultDiv.innerHTML = `
                    <i class="bi bi-check-circle-fill me-2 mt-1"></i>
                    <div>
                        <strong>Cấu hình SSL hoạt động chính xác!</strong><br>
                        <small class="d-block mt-1">- Nhà phát hành thực tế: ${data.issuer}</small>
                        <small class="d-block">- Ngày hết hạn thực tế: ${data.valid_to}</small>
                    </div>
                `;
            } else {
                resultDiv.className = "mt-3 alert alert-danger d-flex align-items-start";
                resultDiv.innerHTML = `
                    <i class="bi bi-exclamation-triangle-fill me-2 mt-1"></i>
                    <div><strong>Lỗi xác thực cài đặt:</strong> ${data.message || data.error}</div>
                `;
            }
        }).catch(err => {
        resultDiv.className = "mt-3 alert alert-danger";
        resultDiv.innerHTML = "Lỗi mạng hoặc không thể kết nối tới API hệ thống.";
    });
}

/**
 * MỚI: Gửi yêu cầu xóa bản ghi chứng chỉ lên Backend
 */
function deleteCertificate(certId) {
    if (confirm("Bạn có chắc chắn muốn xóa chứng chỉ này vĩnh viễn khỏi hệ thống quản lý?")) {
        fetch(`/ssl/api/certificates/${certId}/delete/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            }
        })
            .then(res => res.json())
            .then(data => {
                if (data.message) {
                    alert(data.message);
                    // Điều hướng quay lại kho lưu trữ danh sách SSL
                    window.location.href = "/ssl/certificates/";
                } else {
                    alert("Lỗi hệ thống: " + data.error);
                }
            }).catch(err => {
            alert("Không thể kết nối tới máy chủ để thực hiện lệnh xóa.");
        });
    }
}

/**
 * Kích hoạt luồng chạy tiến trình Deploy chứng chỉ lên Zimbra thông qua API asynchronous
 */
async function startDeploy() {
    lockDeployButton(true);

    const consoleBox = document.getElementById('terminal-console');
    if (consoleBox) {
        consoleBox.textContent = ">>> Đang gửi yêu cầu khởi tạo phiên làm việc SSH đến máy chủ Zimbra...\n";
    }

    const result = await fetchJSON(window.CERT_DETAIL_URLS.apiTriggerDeploy, {method: 'POST'});
    if (result.ok) {
        updateStatusBadge('deploying', 'Đang deploy');
        startPollingLog();
    } else {
        if (consoleBox) {
            consoleBox.textContent += `[LỖI HỆ THỐNG] Không thể kích hoạt Deploy: ${result.data.error}\n`;
        }
        lockDeployButton(false);
    }
}

/**
 * Bắt đầu thiết lập Interval Polling cập nhật log liên tục từ cơ sở dữ liệu
 */
function startPollingLog() {
    if (logInterval) clearInterval(logInterval);

    logInterval = setInterval(async () => {
        const result = await fetchJSON(window.CERT_DETAIL_URLS.apiGetRealtimeLog, {method: 'GET'});
        if (!result.ok) return;

        const data = result.data;
        const consoleBox = document.getElementById('terminal-console');

        if (consoleBox) {
            consoleBox.textContent = data.deploy_log || '';
            consoleBox.scrollTop = consoleBox.scrollHeight;
        }

        // Nếu backend thông báo tiến trình nền đã hoàn tất (không còn trạng thái 'deploying')
        if (data.status !== 'deploying') {
            clearInterval(logInterval);
            logInterval = null;

            updateStatusBadge(data.status, data.status_display);
            lockDeployButton(false);
            reloadDeployHistory();

            // ✅ THÊM: Reload sau 2 giây (chỉ khi thành công)
            if (data.status === 'deployed') {
                setTimeout(() => {
                    window.location.reload();
                }, 1000); // 2 giây
            }
        }
    }, 1500); // Tần suất quét 1.5 giây một lần để tối ưu tài nguyên IO máy chủ
}

/**
 * Gọi API tải lại danh sách lịch sử cấu hình deploy trong quá khứ
 */
async function reloadDeployHistory() {
    const tableBody = document.getElementById('deploy-history-body');
    if (!tableBody) return;

    const result = await fetchJSON(window.CERT_DETAIL_URLS.apiGetDeployHistory, {method: 'GET'});
    if (!result.ok) {
        tableBody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Không thể tải danh sách lịch sử.</td></tr>`;
        return;
    }

    const historyData = result.data.history || [];
    if (historyData.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Chưa ghi nhận lịch sử triển khai nào cho chứng chỉ này.</td></tr>`;
        return;
    }

    tableBody.innerHTML = historyData.map(h => {
        let badgeClass = h.status === 'success' ? 'bg-success' : 'bg-danger';
        return `
            <tr>
                <td class="font-monospace small">#${h.id}</td>
                <td><span class="badge ${badgeClass}">${h.status_display}</span></td>
                <td class="small">${h.triggered_by}</td>
                <td class="font-monospace small">${h.started_at}</td>
                <td class="font-monospace small">${h.finished_at || '--:--'}</td>
                <td class="text-center">
                    <button class="btn btn-outline-secondary btn-sm btn-view-log-trigger py-0 px-2 fw-semibold" 
                            data-history-id="${h.id}" title="Xem chi tiết log">
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

    if (contentBox) {
        contentBox.textContent = "Đang tải dữ liệu log từ cơ sở dữ liệu...";
    }
    toggleModal('history-log-modal', true);

    const result = await fetchJSON(url, {method: 'GET'});
    if (result.ok && contentBox) {
        contentBox.textContent = result.data.log_snapshot || '(Lần deploy này không ghi nhận cấu hình log lưu lại.)';
    } else if (contentBox) {
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
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Đang triển khai...';
    } else {
        btn.classList.remove('disabled');
        btn.innerHTML = '<i class="bi bi-rocket-takeoff me-1"></i>Triển khai ngay lên Zimbra';
    }
}

/**
 * Cập nhật màu sắc CSS & Text động cho Badge Trạng thái hiện tại
 */
function updateStatusBadge(status, displayText) {
    const badge = document.getElementById('cert-status-badge');
    if (!badge) return;

    badge.innerText = displayText;
    badge.className = "badge";

    if (status === 'deployed') {
        badge.classList.add('bg-success');
    } else if (status === 'deploying') {
        badge.classList.add('bg-info');
    } else if (status === 'failed') {
        badge.classList.add('bg-danger');
    } else {
        badge.classList.add('bg-secondary');
    }
}