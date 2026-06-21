/**
 * monitor_metric.js - Nâng cấp Realtime Hybrid (WebSocket + Fallback Polling)
 */

const API_METRIC_URL = '/monitor/api/metric/';
let currentView = 'grid';

// Cấu hình Polling Fallback
let reloadCountdown = 30;
let countdownInterval = null;
let isPollingActive = false; // Cờ kiểm soát trạng thái Polling

// Cấu hình WebSocket
let socket = null;
const wsScheme = window.location.protocol === "https:" ? "wss://" : "ws://";
const wsUrl = wsScheme + window.location.host + "/ws/monitor/metrics/";

document.addEventListener('DOMContentLoaded', () => {
    // Tải dữ liệu lần đầu tiên để tránh màn hình trống
    loadMetricsByHTTP();

    // Khởi tạo kết nối Realtime ưu tiên
    initWebSocket();

    // Lắng nghe Form lọc dữ liệu
    const filterForm = document.getElementById('filterForm');
    if (filterForm) {
        filterForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (isPollingActive) {
                loadMetricsByHTTP();
                resetCountdown();
            } else {
                // Nếu đang dùng Socket, gửi yêu cầu lọc thông qua HTTP hoặc tái thiết lập
                loadMetricsByHTTP();
            }
        });
    }

    // Sự kiện nút làm mới thủ công
    const btnRefresh = document.getElementById('btnRefresh');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            loadMetricsByHTTP();
            if (isPollingActive) resetCountdown();
        });
    }
});

/** Khởi tạo kết nối WebSocket Realtime */
function initWebSocket() {
    console.log("Đang kết nối WebSocket Realtime: " + wsUrl);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("⚡ Kết nối WebSocket thành công. Đang ở chế độ REALTIME.");
        stopPollingFallback(); // Tắt polling nếu đang chạy
        updateConnectionStatus(true);
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        processAndRender(data);
    };

    socket.onerror = (error) => {
        console.error("❌ WebSocket lỗi:", error);
    };

    socket.onclose = (e) => {
        console.warn(`⚠️ WebSocket bị đóng (${e.code}). Chuyển cấu hình sang tự động POLLING (30s)...`);
        updateConnectionStatus(false);
        startPollingFallback(); // Kích hoạt cơ chế Fallback dự phòng ngay lập tức
    };
}

/** Cập nhật nhãn trạng thái kết nối lên UI */
function updateConnectionStatus(isRealtime) {
    const label = document.getElementById('elkClusterLabel');
    if (!label) return;
    if (isRealtime) {
        label.innerHTML = `<span class="badge bg-success"><i class="bi bi-lightning-charge-fill me-1"></i>Realtime Đang Bật</span>`;
    } else {
        label.innerHTML = `<span class="badge bg-warning text-dark"><i class="bi bi-clock-history me-1"></i>Dự phòng Polling (30s)</span>`;
    }
}

/** Bắt đầu kích hoạt vòng lặp Polling dự phòng */
function startPollingFallback() {
    if (isPollingActive) return;
    isPollingActive = true;
    resetCountdown();

    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
        reloadCountdown--;
        // Cập nhật text đếm ngược nếu cần hiển thị ra HTML
        const countdownEl = document.getElementById('countdown');
        if (countdownEl) countdownEl.textContent = reloadCountdown;

        if (reloadCountdown <= 0) {
            loadMetricsByHTTP();
            reloadCountdown = 30;
        }
    }, 1000);
}

/** Tắt vòng lặp Polling khi WebSocket khôi phục thành công */
function stopPollingFallback() {
    isPollingActive = false;
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
}

function resetCountdown() {
    reloadCountdown = 30;
}

/** Hàm lấy dữ liệu qua đường HTTP truyền thống khi Socket sập */
async function loadMetricsByHTTP() {
    const queryStr = buildQueryParams();
    try {
        const response = await fetch(`${API_METRIC_URL}?${queryStr}`);
        if (!response.ok) throw new Error(`Mã lỗi HTTP: ${response.status}`);
        const data = await response.json();
        processAndRender(data);
    } catch (error) {
        setErrorState(error.message || 'Lỗi truy vấn dữ liệu hạ tầng.');
    }
}

/** Xử lý gom nhóm logic Render dùng chung cho cả Socket lẫn HTTP */
function processAndRender(data) {
    const rawItems = data.items || [];

    // Nhóm Host để lấy trạng thái Snapshot mới nhất của server
    const uniqueHostsMap = new Map();
    rawItems.forEach(item => {
        if (item.hostname && !uniqueHostsMap.has(item.hostname)) {
            uniqueHostsMap.set(item.hostname, item);
        }
    });
    const finalHostsList = Array.from(uniqueHostsMap.values());

    // Cập nhật lên UI
    updateSummaryCounters(finalHostsList);
    renderGridView(finalHostsList);
    renderTableView(finalHostsList);
}

// =========================================================================
// CÁC HÀM RENDER AN TOÀN (GIỮ NGUYÊN ĐIỀU KIỆN IF KIỂM TRA ĐỂ TRÁNH LỖI NULL)
// =========================================================================

function updateSummaryCounters(hosts) {
    let ok = 0, warning = 0, critical = 0;
    hosts.forEach(h => {
        if (h.severity === 'critical') critical++;
        else if (h.severity === 'warning') warning++;
        else ok++;
    });

    const elOk = document.getElementById('summary-ok');
    const elWarning = document.getElementById('summary-warning');
    const elCritical = document.getElementById('summary-critical');

    if (elOk) elOk.textContent = ok;
    if (elWarning) elWarning.textContent = warning;
    if (elCritical) elCritical.textContent = critical;
}

function renderGridView(hosts) {
    const container = document.getElementById('view-grid-container');
    if (!container) return;

    if (hosts.length === 0) {
        container.innerHTML = `<div class="col-12 text-center text-muted py-5"><i class="bi bi-inbox fs-2"></i><br>Không có máy chủ nào thỏa mãn điều kiện lọc.</div>`;
        return;
    }

    container.innerHTML = hosts.map(h => {
        let borderClass = h.severity === 'critical' ? 'card-critical' : (h.severity === 'warning' ? 'card-warning' : 'card-ok');
        let badgeClass = h.severity === 'critical' ? 'severity-badge-critical' : (h.severity === 'warning' ? 'severity-badge-warning' : 'severity-badge-ok');
        let zimbraStatus = (h.zimbra_not_running_count > 0) ? `text-danger fw-bold` : `text-success`;

        return `
            <div class="col-md-4">
                <div class="card border-0 shadow-sm h-100 ${borderClass}">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <div>
                                <h6 class="fw-bold text-dark mb-0">${escapeHtmlText(h.hostname)}</h6>
                                <small class="text-muted font-monospace" style="font-size:0.75rem;"><i class="bi bi-clock me-1"></i>${formatTimestamp(h.timestamp)}</small>
                            </div>
                            <span class="badge ${badgeClass} text-uppercase font-monospace px-2 py-1" style="font-size:0.7rem;">${h.severity}</span>
                        </div>
                        <div class="mb-2">
                            <div class="d-flex justify-content-between small mb-1"><span>Sử dụng CPU</span><span class="fw-bold">${formatPercent(h.cpu)}</span></div>
                            <div class="progress"><div class="progress-bar ${h.cpu >= 75 ? 'bg-danger' : 'bg-primary'}" style="width: ${h.cpu || 0}%"></div></div>
                        </div>
                        <div class="mb-2">
                            <div class="d-flex justify-content-between small mb-1"><span>Sử dụng RAM</span><span class="fw-bold">${formatPercent(h.ram)}</span></div>
                            <div class="progress"><div class="progress-bar ${h.ram >= 80 ? 'bg-danger' : 'bg-success'}" style="width: ${h.ram || 0}%"></div></div>
                        </div>
                        <div class="mb-3">
                            <div class="d-flex justify-content-between small mb-1"><span>Dung lượng Disk</span><span class="fw-bold">${formatPercent(h.disk)}</span></div>
                            <div class="progress"><div class="progress-bar bg-warning" style="width: ${h.disk || 0}%"></div></div>
                        </div>
                        <div class="pt-2 border-top d-flex justify-content-between align-items-center small">
                            <div><i class="bi bi-envelope-paper me-1"></i>Queue: <span class="badge bg-secondary">${h.queue || 0}</span></div>
                            <div class="${zimbraStatus}">Lỗi dịch vụ: ${h.zimbra_not_running_count || 0}</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderTableView(hosts) {
    const tbody = document.getElementById('metricTableBody');
    if (!tbody) return;

    if (hosts.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted py-4">Không có máy chủ thỏa mãn điều kiện.</td></tr>`;
        return;
    }

    tbody.innerHTML = hosts.map(h => {
        let badgeClass = h.severity === 'critical' ? 'severity-badge-critical' : (h.severity === 'warning' ? 'severity-badge-warning' : 'severity-badge-ok');
        return `
            <tr class="small">
                <td class="ps-3 text-muted font-monospace">${formatTimestamp(h.timestamp)}</td>
                <td class="fw-bold">${escapeHtmlText(h.hostname)}</td>
                <td>${formatPercent(h.cpu)}</td>
                <td>${formatPercent(h.ram)}</td>
                <td>${formatPercent(h.disk)}</td>
                <td><span class="badge bg-dark">${h.queue || 0}</span></td>
                <td><span class="${h.zimbra_not_running_count > 0 ? 'text-danger fw-bold' : 'text-success'}">${h.zimbra_not_running_count > 0 ? 'Lỗi' : 'Ổn định'}</span></td>
                <td><span class="badge ${badgeClass}">${h.severity}</span></td>
                <td class="text-end pe-3"><a href="/monitor/host/${encodeURIComponent(h.hostname)}/detail/" class="btn btn-sm btn-outline-dark py-0 px-2"><i class="bi bi-eye"></i></a></td>
            </tr>
        `;
    }).join('');
}

function buildQueryParams() {
    const rangeTypeEl = document.getElementById('filterRangeType');
    const rangeValueEl = document.getElementById('filterRangeValue');
    const severityEl = document.getElementById('filterSeverity');
    const hostnameEl = document.getElementById('filterHostname');

    const rangeType = rangeTypeEl ? rangeTypeEl.value : 'hours';
    let rangeValue = rangeValueEl ? rangeValueEl.value.trim() : '24';
    if (!rangeValue || isNaN(rangeValue)) rangeValue = '24';

    let params = `${rangeType}=${rangeValue}`;
    if (severityEl && severityEl.value) params += `&severity=${severityEl.value}`;
    if (hostnameEl && hostnameEl.value.trim()) params += `&hostname=${encodeURIComponent(hostnameEl.value.trim())}`;
    return params;
}

function setErrorState(msg) {
    const grid = document.getElementById('view-grid-container');
    if (grid) grid.innerHTML = `<div class="col-12 text-center text-danger py-5"><i class="bi bi-exclamation-triangle-fill me-1"></i>${escapeHtmlText(msg)}</div>`;
}

function formatPercent(val) { return (val === undefined || val === null) ? '-' : `${Number(val).toFixed(1)}%`; }
function escapeHtmlText(str) { return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''; }
function formatTimestamp(isoStr) {
    if (!isoStr) return '-';
    const d = new Date(isoStr);
    return isNaN(d.getTime()) ? isoStr : d.toLocaleString('vi-VN');
}

window.switchView = function(viewType) {
    currentView = viewType;
    const gridContainer = document.getElementById('view-grid-container');
    const tableContainer = document.getElementById('view-table-container');
    if (viewType === 'grid') {
        if (gridContainer) gridContainer.classList.remove('d-none');
        if (tableContainer) tableContainer.classList.add('d-none');
    } else {
        if (gridContainer) gridContainer.classList.add('d-none');
        if (tableContainer) tableContainer.classList.remove('d-none');
    }
};