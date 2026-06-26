/**
 * monitor_audit.js
 * Logic trang Audit Log (nhật ký hành động quản trị Zimbra) -- dạng bảng,
 * KHÔNG có realtime WebSocket (khác monitor_metric.js) vì audit log là
 * nhật ký tra cứu lịch sử, không cần cập nhật liên tục từng giây.
 *
 * PHÂN TRANG: dạng "tải thêm khi kéo scroll" (infinite scroll), ĐỒNG BỘ
 * cơ chế với monitor_mailbox.js -- dùng IntersectionObserver quan sát 1
 * dòng "sentinel" vô hình ở cuối bảng, tự động tải trang kế tiếp và NỐI
 * thêm dòng vào tbody khi người dùng kéo gần tới cuối.
 */

const API_AUDIT_URL = '/monitor/api/audit/';

window.MONITOR_IS_SUPERUSER = window.MONITOR_IS_SUPERUSER || false;
window.MONITOR_TENANT_ID = null; // Superuser: chưa chọn gì khi tải trang lần đầu.
window.MONITOR_USER_TENANT_ID = window.MONITOR_USER_TENANT_ID || null;

const AUDIT_PAGE_SIZE = 50;

// State phân trang -- reset về trang 1 + xóa dữ liệu cũ mỗi khi đổi filter
// (xem resetAndLoadAudit()); tăng dần khi observer kích hoạt load thêm.
let auditCurrentPage = 1;
let auditTotalPages = 1;
let auditIsLoading = false;   // chặn gọi API trùng lặp khi observer bắn liên tục
let auditObserver = null;

function hasActiveScope() {
    if (!window.MONITOR_IS_SUPERUSER) return true;
    return !!window.MONITOR_TENANT_ID;
}

/** Tenant dùng để build URL gọi API chi tiết (modal) -- giống renderHostDetailLink ở monitor_metric.js. */
function currentTenantIdForDetail() {
    return window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;
}

document.addEventListener('DOMContentLoaded', () => {
    setupAuditScrollObserver();

    if (hasActiveScope()) {
        resetAndLoadAudit();
    } else {
        renderSelectTenantPlaceholder();
    }

    const filterForm = document.getElementById('auditFilterForm');
    if (filterForm) {
        filterForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (hasActiveScope()) resetAndLoadAudit();
        });
    }

    const btnRefresh = document.getElementById('btnRefreshAudit');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            if (hasActiveScope()) resetAndLoadAudit();
        });
    }

    const selectTenant = document.getElementById('selectAuditTenant');
    if (selectTenant) {
        selectTenant.addEventListener('change', () => {
            window.MONITOR_TENANT_ID = selectTenant.value ? parseInt(selectTenant.value, 10) : null;
            if (hasActiveScope()) {
                resetAndLoadAudit();
            } else {
                renderSelectTenantPlaceholder();
            }
        });
    }
});

/**
 * Tạo 1 dòng "sentinel" (vô hình, cao 1px) ngay sau tbody, và 1
 * IntersectionObserver theo dõi dòng đó. Khi dòng lọt vào viewport, tự
 * gọi loadMoreAuditLogs() -- chỉ tạo observer 1 LẦN DUY NHẤT khi trang
 * load, không cần tạo lại mỗi lần fetch.
 */
function setupAuditScrollObserver() {
    const tbody = document.getElementById('auditTableBody');
    if (!tbody) return;

    auditObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) loadMoreAuditLogs();
        });
    }, { root: null, rootMargin: '0px 0px 200px 0px', threshold: 0 });
    // rootMargin 200px: bắt đầu tải SỚM hơn 200px trước khi sentinel thực
    // sự hiện ra, tránh cảm giác giật/khoảng trống chờ tải khi cuộn nhanh.
}

/** Đặt lại dòng sentinel ở cuối tbody và (re-)đăng ký observer theo dõi nó. */
function ensureAuditSentinel() {
    const tbody = document.getElementById('auditTableBody');
    let sentinel = document.getElementById('auditScrollSentinel');
    if (sentinel) sentinel.remove();

    sentinel = document.createElement('tr');
    sentinel.id = 'auditScrollSentinel';
    sentinel.innerHTML = '<td colspan="8" style="height:1px;padding:0;border:0;"></td>';
    tbody.appendChild(sentinel);

    if (auditObserver) auditObserver.observe(sentinel);
}

/** Đổi filter (tenant/submit form/làm mới) -- xóa dữ liệu cũ, quay về trang 1, tải lại từ đầu. */
function resetAndLoadAudit() {
    auditCurrentPage = 1;
    auditTotalPages = 1;
    const tbody = document.getElementById('auditTableBody');
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>Đang truy xuất nhật ký...</td></tr>`;
    loadAuditPage(true);
}

/** Observer gọi hàm này khi cuộn gần cuối bảng -- chỉ tải tiếp nếu còn trang và không đang tải. */
function loadMoreAuditLogs() {
    if (auditIsLoading) return;
    if (auditCurrentPage >= auditTotalPages) return; // đã tải hết, không còn trang nào
    auditCurrentPage += 1;
    loadAuditPage(false);
}

function renderSelectTenantPlaceholder() {
    const tbody = document.getElementById('auditTableBody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Vui lòng chọn Tổ chức (Tenant) để xem nhật ký.</td></tr>`;
    const footer = document.getElementById('auditLoadFooter');
    if (footer) footer.innerHTML = '';
}

function buildAuditQueryParams() {
    const dateFromEl = document.getElementById('auditDateFrom');
    const dateToEl = document.getElementById('auditDateTo');
    const categoryEl = document.getElementById('auditActionCategory');
    const keywordEl = document.getElementById('auditKeyword');

    let params = '';
    const dateFrom = dateFromEl ? dateFromEl.value : '';
    const dateTo = dateToEl ? dateToEl.value : '';

    if (dateFrom) params += `date_from=${encodeURIComponent(dateFrom)}`;
    if (dateTo) params += `${params ? '&' : ''}date_to=${encodeURIComponent(dateTo)}`;

    // Không chọn ngày nào cả -> giữ hành vi mặc định cũ: 24h gần nhất
    // (base.py: resolve_time_range trả về 24h nếu hours/days/date đều rỗng).
    if (!dateFrom && !dateTo) params += `${params ? '&' : ''}hours=24`;

    if (categoryEl && categoryEl.value) params += `&action_category=${encodeURIComponent(categoryEl.value)}`;
    if (keywordEl && keywordEl.value.trim()) params += `&keyword=${encodeURIComponent(keywordEl.value.trim())}`;
    if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) params += `&tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}`;
    params += `&page=${auditCurrentPage}&page_size=${AUDIT_PAGE_SIZE}`;
    return params;
}

/**
 * isFirstLoad=true: trang 1, tbody đang được XÓA SẠCH và render lại từ đầu.
 * isFirstLoad=false: trang kế tiếp do observer kích hoạt, NỐI thêm dòng
 * vào tbody hiện có, không xóa gì cả.
 */
async function loadAuditPage(isFirstLoad) {
    auditIsLoading = true;
    renderAuditLoadFooter('loading');

    const queryStr = buildAuditQueryParams();
    try {
        const response = await fetch(`${API_AUDIT_URL}?${queryStr}`);
        if (!response.ok) throw new Error(`Mã lỗi HTTP: ${response.status}`);
        const data = await response.json();

        auditTotalPages = data.total_pages || 1;
        appendAuditRows(data.items || [], isFirstLoad);
        renderAuditLoadFooter('idle', data.total || 0);
    } catch (error) {
        const tbody = document.getElementById('auditTableBody');
        if (isFirstLoad) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">${escapeHtmlText(error.message || 'Lỗi truy vấn dữ liệu.')}</td></tr>`;
        }
        renderAuditLoadFooter('error', 0, error.message);
        // Lùi lại page để lần kéo scroll tiếp theo có thể thử lại trang
        // vừa lỗi, không bị "kẹt" mãi ở trang đã tăng nhưng chưa tải được.
        if (!isFirstLoad) auditCurrentPage -= 1;
    } finally {
        auditIsLoading = false;
    }
}

/** Hiển thị trạng thái dưới bảng: đang tải / đã hết dữ liệu / lỗi -- chỉ báo trực quan cho infinite scroll. */
function renderAuditLoadFooter(state, total, errorMessage) {
    let footer = document.getElementById('auditLoadFooter');
    if (!footer) {
        const tableCard = document.getElementById('auditTableBody').closest('.card');
        footer = document.createElement('div');
        footer.id = 'auditLoadFooter';
        footer.className = 'text-center text-muted small py-3';
        tableCard.insertAdjacentElement('afterend', footer);
    }

    if (state === 'loading') {
        footer.innerHTML = `<div class="spinner-border spinner-border-sm me-2"></div>Đang tải thêm...`;
    } else if (state === 'error') {
        footer.innerHTML = `<span class="text-danger">${escapeHtmlText(errorMessage || 'Lỗi tải dữ liệu.')}</span>`;
    } else if (auditCurrentPage >= auditTotalPages) {
        footer.innerHTML = total > 0
            ? `Đã hiển thị tất cả ${total} bản ghi.`
            : '';
    } else {
        footer.innerHTML = `<small>Kéo xuống để tải thêm...</small>`;
    }
}

function auditRowHtml(item) {
    const performedBy = item.admin_email || item.auth_email || '-';
    const target = item.target_email || '-';
    const category = item.action_category || '-';
    const command = item.command || '-';
    const ip = item.client_ip || '-';
    const t = item.timestamp ? String(item.timestamp).replace('T', ' ').substring(0, 19) : (item['@timestamp'] || '-');

    let statusBadge = '<span class="badge bg-secondary">-</span>';
    if (item.login_status === 'success') {
        statusBadge = '<span class="badge bg-success">Thành công</span>';
    } else if (item.login_status === 'failed') {
        statusBadge = `<span class="badge bg-danger">Thất bại${item.error_type ? ' - ' + escapeHtmlText(item.error_type) : ''}</span>`;
    }

    return `
        <tr class="small" style="cursor:pointer" onclick="openAuditOriginLog('${escapeAttr(item._id)}')">
            <td class="ps-3 text-muted font-monospace">${escapeHtmlText(t)}</td>
            <td class="fw-bold">${escapeHtmlText(performedBy)}</td>
            <td><span class="badge bg-dark font-monospace">${escapeHtmlText(command)}</span></td>
            <td>${escapeHtmlText(category)}</td>
            <td>${escapeHtmlText(target)}</td>
            <td class="font-monospace text-muted">${escapeHtmlText(ip)}</td>
            <td>${statusBadge}</td>
            <td class="text-end pe-3"><i class="bi bi-eye text-muted"></i></td>
        </tr>
    `;
}

/**
 * isFirstLoad=true: xóa sạch tbody rồi render items từ đầu. isFirstLoad=
 * false: giữ nguyên dòng đã có, CHÈN thêm dòng mới vào TRƯỚC dòng
 * sentinel (luôn phải nằm cuối cùng để observer tiếp tục theo dõi đúng
 * vị trí).
 */
function appendAuditRows(items, isFirstLoad) {
    const tbody = document.getElementById('auditTableBody');

    if (isFirstLoad) {
        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Không có nhật ký nào thỏa mãn điều kiện lọc.</td></tr>`;
            ensureAuditSentinel();
            return;
        }
        tbody.innerHTML = items.map(auditRowHtml).join('');
        ensureAuditSentinel();
        return;
    }

    if (items.length === 0) return;

    const sentinel = document.getElementById('auditScrollSentinel');
    const rowsHtml = items.map(auditRowHtml).join('');
    if (sentinel) {
        sentinel.insertAdjacentHTML('beforebegin', rowsHtml);
    } else {
        tbody.insertAdjacentHTML('beforeend', rowsHtml);
        ensureAuditSentinel();
    }
}

/** Mở modal xem log gốc -- gọi API riêng theo tenant_id (path) + doc_id. */
async function openAuditOriginLog(docId) {
    const tenantId = currentTenantIdForDetail();
    const metaEl = document.getElementById('auditOriginLogMeta');
    const contentEl = document.getElementById('auditOriginLogContent');

    if (!tenantId) {
        contentEl.textContent = 'Không xác định được tổ chức để truy vấn.';
        metaEl.textContent = '';
    } else {
        contentEl.textContent = 'Đang tải...';
        metaEl.textContent = '';

        try {
            const url = `/monitor/api/tenant/${encodeURIComponent(tenantId)}/audit/${encodeURIComponent(docId)}/`;
            const res = await fetch(url);
            const data = await res.json();

            if (data.error) {
                contentEl.textContent = data.error;
            } else {
                // Hiển thị NGUYÊN VĂN message (dòng log thô gốc từ audit.log).
                contentEl.textContent = data.message || '(Không có nội dung message)';
                const t = data.timestamp ? String(data.timestamp).replace('T', ' ').substring(0, 19) : '-';
                metaEl.innerHTML = `<strong>Host:</strong> ${escapeHtmlText(data.host && data.host.hostname || '-')}
                    &nbsp;|&nbsp; <strong>Thời gian:</strong> ${escapeHtmlText(t)}
                    &nbsp;|&nbsp; <strong>Document ID:</strong> <span class="font-monospace">${escapeHtmlText(docId)}</span>`;
            }
        } catch (e) {
            contentEl.textContent = 'Lỗi hệ thống, không thể tải nội dung log.';
        }
    }

    const modalEl = document.getElementById('modalAuditOriginLog');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
}

function escapeHtmlText(str) { return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''; }
function escapeAttr(str) { return str ? String(str).replace(/'/g, "\\'") : ''; }