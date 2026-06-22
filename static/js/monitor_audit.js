/**
 * monitor_audit.js
 * Logic trang Audit Log (nhật ký hành động quản trị Zimbra) -- dạng bảng,
 * KHÔNG có realtime WebSocket (khác monitor_metric.js) vì audit log là
 * nhật ký tra cứu lịch sử, không cần cập nhật liên tục từng giây.
 */

const API_AUDIT_URL = '/monitor/api/audit/';

window.MONITOR_IS_SUPERUSER = window.MONITOR_IS_SUPERUSER || false;
window.MONITOR_TENANT_ID = null; // Superuser: chưa chọn gì khi tải trang lần đầu.
window.MONITOR_USER_TENANT_ID = window.MONITOR_USER_TENANT_ID || null;

function hasActiveScope() {
    if (!window.MONITOR_IS_SUPERUSER) return true;
    return !!window.MONITOR_TENANT_ID;
}

/** Tenant dùng để build URL gọi API chi tiết (modal) -- giống renderHostDetailLink ở monitor_metric.js. */
function currentTenantIdForDetail() {
    return window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;
}

document.addEventListener('DOMContentLoaded', () => {
    if (hasActiveScope()) {
        loadAuditLogs();
    } else {
        renderSelectTenantPlaceholder();
    }

    const filterForm = document.getElementById('auditFilterForm');
    if (filterForm) {
        filterForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (hasActiveScope()) loadAuditLogs();
        });
    }

    const btnRefresh = document.getElementById('btnRefreshAudit');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            if (hasActiveScope()) loadAuditLogs();
        });
    }

    const selectTenant = document.getElementById('selectAuditTenant');
    if (selectTenant) {
        selectTenant.addEventListener('change', () => {
            window.MONITOR_TENANT_ID = selectTenant.value ? parseInt(selectTenant.value, 10) : null;
            if (hasActiveScope()) {
                loadAuditLogs();
            } else {
                renderSelectTenantPlaceholder();
            }
        });
    }
});

function renderSelectTenantPlaceholder() {
    const tbody = document.getElementById('auditTableBody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Vui lòng chọn Tổ chức (Tenant) để xem nhật ký.</td></tr>`;
}

function buildAuditQueryParams() {
    const rangeTypeEl = document.getElementById('auditRangeType');
    const rangeValueEl = document.getElementById('auditRangeValue');
    const categoryEl = document.getElementById('auditActionCategory');
    const keywordEl = document.getElementById('auditKeyword');

    const rangeType = rangeTypeEl ? rangeTypeEl.value : 'hours';
    let rangeValue = rangeValueEl ? rangeValueEl.value.trim() : '24';
    if (!rangeValue || isNaN(rangeValue)) rangeValue = '24';

    let params = `${rangeType}=${rangeValue}`;
    if (categoryEl && categoryEl.value) params += `&action_category=${encodeURIComponent(categoryEl.value)}`;
    if (keywordEl && keywordEl.value.trim()) params += `&keyword=${encodeURIComponent(keywordEl.value.trim())}`;
    if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) params += `&tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}`;
    return params;
}

async function loadAuditLogs() {
    const tbody = document.getElementById('auditTableBody');
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>Đang truy xuất nhật ký...</td></tr>`;

    const queryStr = buildAuditQueryParams();
    try {
        const response = await fetch(`${API_AUDIT_URL}?${queryStr}`);
        if (!response.ok) throw new Error(`Mã lỗi HTTP: ${response.status}`);
        const data = await response.json();
        renderAuditTable(data.items || []);
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">${escapeHtmlText(error.message || 'Lỗi truy vấn dữ liệu.')}</td></tr>`;
    }
}

function renderAuditTable(items) {
    const tbody = document.getElementById('auditTableBody');

    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Không có nhật ký nào thỏa mãn điều kiện lọc.</td></tr>`;
        return;
    }

    tbody.innerHTML = items.map(item => {
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
    }).join('');
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