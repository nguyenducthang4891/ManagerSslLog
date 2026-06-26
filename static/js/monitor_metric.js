/**
 * monitor_metric.js - Nâng cấp Realtime Hybrid (WebSocket + Fallback Polling)
 *
 * THAY ĐỔI BẢO MẬT: WebSocket giờ yêu cầu "subscribe" kèm tenant_id sau khi
 * connect (xem consumers.py). Với Superuser, biến window.MONITOR_TENANT_ID
 * phải được set TRƯỚC khi DOMContentLoaded (template metric.html render ra)
 * -- nếu null/undefined, không subscribe gì cả, không gọi API, chỉ hiện
 * placeholder yêu cầu chọn tenant.
 *
 * THAY ĐỔI HIỂN THỊ RX/TX: dùng net_rx_bps/net_tx_bps (tốc độ TỨC THỜI,
 * đơn vị bits/giây, do agent tự tính bằng cách lưu cache giá trị counter +
 * timestamp của lần chạy trước rồi tính delta -- xem agent_metrics.sh và
 * metric.conf) -- KHÔNG còn dùng net_rx/net_tx (counter lũy kế từ lúc
 * interface up, dễ hiểu lầm là tốc độ hiện tại trong khi thực ra là tổng
 * dồn). Hiển thị theo Mbps/Kbps -- chuẩn ngành mạng, dễ so sánh với băng
 * thông danh định của server (ví dụ "1 Gbps link").
 */

const API_METRIC_URL = '/monitor/api/metric/';
let currentView = 'grid';

// Cấu hình Polling Fallback
let reloadCountdown = 30;
let countdownInterval = null;
let isPollingActive = false; // Cờ kiểm soát trạng thái Polling

// Cấu hình WebSocket
let socket = null;
let wsReconnectTimer = null;
const wsScheme = window.location.protocol === "https:" ? "wss://" : "ws://";
const wsUrl = wsScheme + window.location.host + "/ws/monitor/metrics/";

/**
 * Tenant đang được xem:
 * - Non-superuser: server tự ép theo user.tenant, giá trị này không quan
 *   trọng (consumers.py sẽ bỏ qua và tự lấy user.tenant), nhưng vẫn cần
 *   khác null để code biết "đã có quyền xem, được phép gọi API/subscribe".
 * - Superuser: PHẢI được set qua dropdown chọn tenant (select2) trên
 *   metric.html, ví dụ: window.MONITOR_TENANT_ID = 12; rồi gọi
 *   window.onTenantSelected(12). Mặc định null = chưa chọn = không xem gì.
 */
window.MONITOR_IS_SUPERUSER = window.MONITOR_IS_SUPERUSER || false;
window.MONITOR_TENANT_ID = window.MONITOR_TENANT_ID || null;

/**
 * Tenant CỐ ĐỊNH của user hiện tại -- CHỈ áp dụng cho non-superuser (mỗi
 * non-superuser luôn thuộc đúng 1 tenant). Server-side template
 * (metric.html) phải set giá trị này = request.user.tenant_id.
 *
 * Dùng riêng cho việc build link sang trang chi tiết host (xem
 * renderHostDetailLink) -- KHÁC với MONITOR_TENANT_ID (tenant ĐANG XEM,
 * có thể đổi qua dropdown nếu là superuser). Với superuser, biến này luôn
 * null vì họ không có 1 tenant cố định -- link host detail của superuser
 * phải dùng MONITOR_TENANT_ID (tenant đang chọn) thay thế.
 */
window.MONITOR_USER_TENANT_ID = window.MONITOR_USER_TENANT_ID || null;

function hasActiveScope() {
    if (!window.MONITOR_IS_SUPERUSER) return true; // non-superuser luôn có scope (tenant của họ)
    return !!window.MONITOR_TENANT_ID;
}

/**
 * Build link sang trang chi tiết host, kèm đúng tenant_id trong path
 * (/monitor/tenant/<id>/host/<hostname>/detail/). Nếu chưa xác định được
 * tenant nào để gắn vào link (vd: superuser chưa chọn tenant), trả về nút
 * disabled thay vì tạo link hỏng dẫn tới lỗi 403/404 khi click.
 */
function renderHostDetailLink(hostname) {
    const tenantId = window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;

    if (!tenantId) {
        return `<button class="btn btn-sm btn-outline-secondary py-0 px-2 disabled" disabled title="Không xác định được tổ chức"><i class="bi bi-eye-slash"></i></button>`;
    }

    const url = `/monitor/tenant/${encodeURIComponent(tenantId)}/host/${encodeURIComponent(hostname)}/detail/`;
    return `<a href="${url}" class="btn btn-sm btn-outline-dark py-0 px-2"><i class="bi bi-eye"></i></a>`;
}

/**
 * Bản FULL-WIDTH của renderHostDetailLink(), dùng cho footer card ở Dạng
 * lưới (renderGridView) -- nhiều không gian hơn <td> ở Dạng bảng nên hiển
 * thị rõ chữ "Xem chi tiết log" thay vì chỉ icon nhỏ. Dùng LẠI đúng logic
 * xác định tenantId (không lặp lại, không tách rời 2 nguồn sự thật).
 */
function renderHostDetailLinkBlock(hostname) {
    const tenantId = window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;

    if (!tenantId) {
        return `<button class="btn btn-sm btn-outline-secondary w-100 disabled" disabled title="Không xác định được tổ chức"><i class="bi bi-eye-slash me-1"></i>Không xác định được tổ chức</button>`;
    }

    const url = `/monitor/tenant/${encodeURIComponent(tenantId)}/host/${encodeURIComponent(hostname)}/detail/`;
    return `<a href="${url}" class="btn btn-sm btn-outline-dark w-100"><i class="bi bi-eye me-1"></i>Xem chi tiết log</a>`;
}

document.addEventListener('DOMContentLoaded', () => {
    if (hasActiveScope()) {
        loadMetricsByHTTP();
        initWebSocket();
    } else {
        renderSelectTenantPlaceholder();
    }

    const btnRefresh = document.getElementById('btnRefresh');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            if (!hasActiveScope()) return;
            loadMetricsByHTTP();
            if (isPollingActive) resetCountdown();
        });
    }
});

/**
 * Gọi khi Superuser chọn 1 tenant từ select2 trên UI (metric.html cần gọi
 * hàm này trong sự kiện 'change' của dropdown).
 * @param {number|null} tenantId
 */
window.onTenantSelected = function(tenantId) {
    window.MONITOR_TENANT_ID = tenantId || null;

    if (!hasActiveScope()) {
        renderSelectTenantPlaceholder();
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({action: 'subscribe', tenant_id: null}));
        }
        return;
    }

    loadMetricsByHTTP();
    resetCountdown();

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({action: 'subscribe', tenant_id: window.MONITOR_TENANT_ID}));
    } else {
        // Nếu socket chưa sẵn sàng (đang kết nối/đang ở polling), khởi tạo lại.
        initWebSocket();
    }
};

function renderSelectTenantPlaceholder() {
    const grid = document.getElementById('view-grid-container');
    const tbody = document.getElementById('metricTableBody');
    const msg = `<div class="col-12 text-center text-muted py-5"><i class="bi bi-funnel fs-2"></i><br>Vui lòng chọn Tổ chức (Tenant) để xem dữ liệu giám sát.</div>`;
    if (grid) grid.innerHTML = msg;
    if (tbody) tbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-4">Vui lòng chọn Tổ chức (Tenant) để xem dữ liệu giám sát.</td></tr>`;
    updateSummaryCounters([]);
}

/** Khởi tạo kết nối WebSocket Realtime */
function initWebSocket() {
    if (!hasActiveScope()) return;

    console.log("Đang kết nối WebSocket Realtime: " + wsUrl);
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("⚡ Kết nối WebSocket thành công. Đang gửi yêu cầu subscribe...");
        stopPollingFallback();
        // Server sẽ tự ép tenant_id đúng quyền với non-superuser; với
        // superuser thì gửi đúng tenant đang chọn trên UI.
        socket.send(JSON.stringify({action: 'subscribe', tenant_id: window.MONITOR_TENANT_ID}));
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data && data.subscribed === false) {
            // Server từ chối (vd: superuser chưa chọn tenant hợp lệ).
            updateConnectionStatus(false);
            return;
        }
        if (data && typeof data.subscribed === 'boolean') {
            updateConnectionStatus(true);
            return;
        }
        processAndRender(data);
    };

    socket.onerror = (error) => {
        console.error("❌ WebSocket lỗi:", error);
    };

    socket.onclose = (e) => {
        console.warn(`⚠️ WebSocket bị đóng (${e.code}). Chuyển cấu hình sang tự động POLLING (30s)...`);
        updateConnectionStatus(false);
        startPollingFallback();

        // Tự động thử kết nối lại sau 5s nếu vẫn còn quyền xem dữ liệu,
        // để không bị kẹt ở polling mãi mãi khi server WS phục hồi.
        if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
        if (e.code !== 4001) { // 4001 = consumers.py từ chối do chưa đăng nhập, không retry
            wsReconnectTimer = setTimeout(() => {
                if (hasActiveScope()) initWebSocket();
            }, 5000);
        }
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
    if (!hasActiveScope()) return;
    isPollingActive = true;
    resetCountdown();

    if (countdownInterval) clearInterval(countdownInterval);
    countdownInterval = setInterval(() => {
        reloadCountdown--;
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
    if (!hasActiveScope()) {
        renderSelectTenantPlaceholder();
        return;
    }

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

/**
 * Xử lý gom nhóm logic Render dùng chung cho cả Socket lẫn HTTP.
 *
 * ĐÃ BỎ FILTER (severity/hostname/khoảng giờ): trang metric.html giờ là
 * dashboard REALTIME THUẦN -- luôn hiển thị TOÀN BỘ host của tenant đang
 * xem, không có khái niệm "lọc rồi giữ kết quả qua mỗi lần cập nhật". Mỗi
 * lần WS đẩy data mới (hoặc HTTP load), danh sách hiển thị luôn là TOÀN BỘ
 * host mới nhất, không qua bước lọc nào.
 */
function processAndRender(data) {
    const rawItems = data.items || [];

    const uniqueHostsMap = new Map();
    rawItems.forEach(item => {
        if (item.hostname && !uniqueHostsMap.has(item.hostname)) {
            uniqueHostsMap.set(item.hostname, item);
        }
    });
    const finalHostsList = Array.from(uniqueHostsMap.values());

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
        container.innerHTML = `<div class="col-12 text-center text-muted py-5"><i class="bi bi-inbox fs-2"></i><br>Chưa có dữ liệu giám sát máy chủ nào.</div>`;
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
                        <div class="d-flex justify-content-between small text-muted mb-2">
                            <div><i class="bi bi-arrow-down-circle me-1"></i>RX: <span class="fw-bold">${formatBitrate(h.net_rx_bps)}</span></div>
                            <div><i class="bi bi-arrow-up-circle me-1"></i>TX: <span class="fw-bold">${formatBitrate(h.net_tx_bps)}</span></div>
                        </div>
                        <div class="pt-2 border-top d-flex justify-content-between align-items-center small">
                            <div><i class="bi bi-envelope-paper me-1"></i>Queue: <span class="badge bg-secondary">${h.queue || 0}</span></div>
                            <div class="${zimbraStatus}">Lỗi dịch vụ: ${h.zimbra_not_running_count || 0}</div>
                        </div>
                        <div class="pt-2 mt-2 border-top">
                            ${renderHostDetailLinkBlock(h.hostname)}
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
        tbody.innerHTML = `<tr><td colspan="11" class="text-center text-muted py-4">Chưa có dữ liệu giám sát máy chủ nào.</td></tr>`;
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
                <td class="font-monospace">${formatBitrate(h.net_rx_bps)}</td>
                <td class="font-monospace">${formatBitrate(h.net_tx_bps)}</td>
                <td><span class="badge bg-dark">${h.queue || 0}</span></td>
                <td><span class="${h.zimbra_not_running_count > 0 ? 'text-danger fw-bold' : 'text-success'}">${h.zimbra_not_running_count > 0 ? 'Lỗi' : 'Ổn định'}</span></td>
                <td><span class="badge ${badgeClass}">${h.severity}</span></td>
                <td class="text-end pe-3">${renderHostDetailLink(h.hostname)}</td>
            </tr>
        `;
    }).join('');
}

/**
 * ĐÃ BỎ FILTER: chỉ còn tenant_id (superuser) -- không còn severity,
 * hostname, hay khoảng giờ tùy chọn. MetricService.query() tự dùng mặc
 * định 24h gần nhất khi không truyền hours/days (xem resolve_time_range
 * trong services/base.py), khớp đúng với khoảng Celery Beat đang quét cho
 * WebSocket -- không cần truyền lại từ client nữa.
 */
function buildQueryParams() {
    let params = '';
    if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) {
        params += `tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}`;
    }
    return params;
}

function setErrorState(msg) {
    const grid = document.getElementById('view-grid-container');
    if (grid) grid.innerHTML = `<div class="col-12 text-center text-danger py-5"><i class="bi bi-exclamation-triangle-fill me-1"></i>${escapeHtmlText(msg)}</div>`;
}

function formatPercent(val) { return (val === undefined || val === null) ? '-' : `${Number(val).toFixed(1)}%`; }

/**
 * Định dạng tốc độ mạng tức thời (đơn vị gốc: bits/giây, do agent tính sẵn
 * trong net_rx_bps/net_tx_bps) thành Mbps/Kbps -- CHUẨN NGÀNH MẠNG dùng
 * bits, KHÁC với dung lượng file/disk dùng bytes. 1 Mbps = 1,000,000 bit/s
 * (dùng hệ số 1000, không phải 1024, vì đây là quy ước chuẩn cho băng
 * thông mạng -- ví dụ link "1 Gbps" luôn hiểu là 1,000,000,000 bit/s).
 */
function formatBitrate(bps) {
    if (bps === undefined || bps === null || isNaN(bps)) return '-';
    const num = Number(bps);
    if (num >= 1000 ** 3) return `${(num / 1000 ** 3).toFixed(2)} Gbps`;
    if (num >= 1000 ** 2) return `${(num / 1000 ** 2).toFixed(2)} Mbps`;
    if (num >= 1000) return `${(num / 1000).toFixed(2)} Kbps`;
    return `${num} bps`;
}

function escapeHtmlText(str) { return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''; }
/**
 * Convert chuỗi timestamp UTC sang giờ Việt Nam (GMT+7) -- ÉP CỨNG
 * timeZone 'Asia/Ho_Chi_Minh', KHÔNG còn dùng toLocaleString('vi-VN')
 * như trước (cách cũ tự convert theo timezone CẤU HÌNH TRÊN MÁY CLIENT,
 * nếu máy người dùng đặt sai timezone hệ thống thì hiển thị vẫn sai dù
 * locale đúng 'vi-VN'). Đồng bộ cách làm với monitor_audit.js/
 * monitor_mailbox.js/monitor_backup.js.
 */
function formatTimestamp(isoStr) {
    if (!isoStr) return '-';
    const date = new Date(isoStr);
    if (isNaN(date.getTime())) return isoStr;

    const formatter = new Intl.DateTimeFormat('vi-VN', {
        timeZone: 'Asia/Ho_Chi_Minh',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
    });
    const parts = formatter.formatToParts(date);
    const get = (type) => parts.find(p => p.type === type)?.value || '';
    return `${get('day')}/${get('month')}/${get('year')} ${get('hour')}:${get('minute')}:${get('second')}`;
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