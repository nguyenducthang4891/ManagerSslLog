/**
 * ⭐ THÊM: Xuất Excel cho Backup
 */

const API_BACKUP_URL = '/monitor/api/backup/';
const API_EXPORT_BACKUP_URL = '/monitor/api/backup/export/excel/';

window.MONITOR_IS_SUPERUSER = window.MONITOR_IS_SUPERUSER || false;
window.MONITOR_TENANT_ID = null;
window.MONITOR_USER_TENANT_ID = window.MONITOR_USER_TENANT_ID || null;

const BACKUP_PAGE_SIZE = 50;

let backupCurrentPage = 1;
let backupTotalPages = 1;
let backupIsLoading = false;
let backupObserver = null;

function hasActiveBackupScope() {
    if (!window.MONITOR_IS_SUPERUSER) return true;
    return !!window.MONITOR_TENANT_ID;
}

function currentBackupTenantIdForDetail() {
    return window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;
}

document.addEventListener('DOMContentLoaded', () => {
    setupBackupScrollObserver();

    if (hasActiveBackupScope()) {
        resetAndLoadBackup();
        loadBackupSummary();
    } else {
        renderSelectBackupTenantPlaceholder();
    }

    const filterForm = document.getElementById('backupFilterForm');
    if (filterForm) {
        filterForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (hasActiveBackupScope()) {
                resetAndLoadBackup();
                loadBackupSummary();
            }
        });
    }

    const btnRefresh = document.getElementById('btnRefreshBackup');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            if (hasActiveBackupScope()) {
                resetAndLoadBackup();
                loadBackupSummary();
            }
        });
    }

    // ⭐ THÊM: Event listener cho nút xuất Excel
    const btnExportBackup = document.getElementById('btnExportBackupExcel');
    if (btnExportBackup) {
        btnExportBackup.addEventListener('click', exportBackupToExcel);
    }

    const selectTenant = document.getElementById('selectBackupTenant');
    if (selectTenant) {
        selectTenant.addEventListener('change', () => {
            window.MONITOR_TENANT_ID = selectTenant.value ? parseInt(selectTenant.value, 10) : null;
            if (hasActiveBackupScope()) {
                resetAndLoadBackup();
                loadBackupSummary();
            } else {
                renderSelectBackupTenantPlaceholder();
            }
        });
    }
});

function setupBackupScrollObserver() {
    const tbody = document.getElementById('backupTableBody');
    if (!tbody) return;

    backupObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) loadMoreBackupLogs();
        });
    }, { root: null, rootMargin: '0px 0px 200px 0px', threshold: 0 });
}

function ensureBackupSentinel() {
    const tbody = document.getElementById('backupTableBody');
    let sentinel = document.getElementById('backupScrollSentinel');
    if (sentinel) sentinel.remove();

    sentinel = document.createElement('tr');
    sentinel.id = 'backupScrollSentinel';
    sentinel.innerHTML = '<td colspan="7" style="height:1px;padding:0;border:0;"></td>';
    tbody.appendChild(sentinel);

    if (backupObserver) backupObserver.observe(sentinel);
}

function resetAndLoadBackup() {
    backupCurrentPage = 1;
    backupTotalPages = 1;
    const tbody = document.getElementById('backupTableBody');
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>Đang truy xuất dữ liệu backup...</td></tr>`;
    loadBackupPage(true);
}

function loadMoreBackupLogs() {
    if (backupIsLoading) return;
    if (backupCurrentPage >= backupTotalPages) return;
    backupCurrentPage += 1;
    loadBackupPage(false);
}

function renderSelectBackupTenantPlaceholder() {
    const tbody = document.getElementById('backupTableBody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Vui lòng chọn Tổ chức (Tenant) để xem dữ liệu backup.</td></tr>`;
}

function buildBackupQueryParams() {
    const dateFromEl = document.getElementById('backupDateFrom');
    const dateToEl = document.getElementById('backupDateTo');
    const modeEl = document.getElementById('backupMode');
    const statusEl = document.getElementById('backupStatus');
    const searchEl = document.getElementById('backupSearchAccount');

    let params = '';
    const dateFrom = dateFromEl ? dateFromEl.value : '';
    const dateTo = dateToEl ? dateToEl.value : '';

    if (dateFrom) params += `date_from=${encodeURIComponent(dateFrom)}`;
    if (dateTo) params += `${params ? '&' : ''}date_to=${encodeURIComponent(dateTo)}`;

    if (!dateFrom && !dateTo) params += `${params ? '&' : ''}hours=24`;

    if (modeEl && modeEl.value) params += `&backup_mode=${encodeURIComponent(modeEl.value)}`;
    if (statusEl && statusEl.value) params += `&status=${encodeURIComponent(statusEl.value)}`;
    if (searchEl && searchEl.value.trim()) params += `&search_account=${encodeURIComponent(searchEl.value.trim())}`;
    if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) params += `&tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}`;
    params += `&page=${backupCurrentPage}&page_size=${BACKUP_PAGE_SIZE}`;
    return params;
}

async function loadBackupPage(isFirstLoad) {
    backupIsLoading = true;
    renderBackupLoadFooter('loading');

    const queryStr = buildBackupQueryParams();
    try {
        const response = await fetch(`${API_BACKUP_URL}?${queryStr}`);
        if (!response.ok) throw new Error(`Mã lỗi HTTP: ${response.status}`);
        const data = await response.json();

        backupTotalPages = data.total_pages || 1;
        appendBackupRows(data.items || [], isFirstLoad);
        renderBackupLoadFooter('idle', data.total || 0);
    } catch (error) {
        const tbody = document.getElementById('backupTableBody');
        if (isFirstLoad) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger py-4">${escapeHtmlText(error.message || 'Lỗi truy vấn dữ liệu.')}</td></tr>`;
        }
        renderBackupLoadFooter('error', 0, error.message);
        if (!isFirstLoad) backupCurrentPage -= 1;
    } finally {
        backupIsLoading = false;
    }
}

function renderBackupLoadFooter(state, total, errorMessage) {
    let footer = document.getElementById('backupLoadFooter');
    if (!footer) {
        const tableCard = document.getElementById('backupTableBody').closest('.card');
        footer = document.createElement('div');
        footer.id = 'backupLoadFooter';
        footer.className = 'text-center text-muted small py-3';
        tableCard.insertAdjacentElement('afterend', footer);
    }

    if (state === 'loading') {
        footer.innerHTML = `<div class="spinner-border spinner-border-sm me-2"></div>Đang tải thêm...`;
    } else if (state === 'error') {
        footer.innerHTML = `<span class="text-danger">${escapeHtmlText(errorMessage || 'Lỗi tải dữ liệu.')}</span>`;
    } else if (backupCurrentPage >= backupTotalPages) {
        footer.innerHTML = total > 0 ? `Đã hiển thị tất cả ${total} bản ghi.` : '';
    } else {
        footer.innerHTML = `<small>Kéo xuống để tải thêm...</small>`;
    }
}

function backupRowHtml(item) {
    const t = item.timestamp ? String(item.timestamp).replace('T', ' ').substring(0, 19) : (item['@timestamp'] || '-');
    const account = item.account || '-';
    const mode = item.backup_mode || '-';
    const status = item.status || '-';
    const size = item.size_bytes ? formatFileSize(item.size_bytes) : '-';
    const duration = item.duration_seconds ? `${item.duration_seconds}s` : '-';

    let statusBadge = '<span class="badge bg-secondary">-</span>';
    if (status === 'SUCCESS') {
        statusBadge = '<span class="badge bg-success">Thành công</span>';
    } else if (status === 'FAILED') {
        statusBadge = '<span class="badge bg-danger">Thất bại</span>';
    } else if (status === 'NO_CONTENT') {
        statusBadge = '<span class="badge bg-warning text-dark">Không có email mới</span>';
    }

    return `
        <tr class="small" style="cursor:pointer" onclick="openBackupOriginLog('${escapeAttr(item._id)}')">
            <td class="ps-3 text-muted font-monospace">${escapeHtmlText(t)}</td>
            <td class="fw-bold">${escapeHtmlText(account)}</td>
            <td><span class="badge bg-dark font-monospace">${escapeHtmlText(mode)}</span></td>
            <td>${statusBadge}</td>
            <td class="font-monospace">${escapeHtmlText(size)}</td>
            <td class="font-monospace text-muted">${escapeHtmlText(duration)}</td>
            <td class="text-end pe-3"><i class="bi bi-eye text-muted"></i></td>
        </tr>
    `;
}

function appendBackupRows(items, isFirstLoad) {
    const tbody = document.getElementById('backupTableBody');

    if (isFirstLoad) {
        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Không có bản ghi backup nào thỏa mãn điều kiện lọc.</td></tr>`;
            ensureBackupSentinel();
            return;
        }
        tbody.innerHTML = items.map(backupRowHtml).join('');
        ensureBackupSentinel();
        return;
    }

    if (items.length === 0) return;

    const sentinel = document.getElementById('backupScrollSentinel');
    const rowsHtml = items.map(backupRowHtml).join('');
    if (sentinel) {
        sentinel.insertAdjacentHTML('beforebegin', rowsHtml);
    } else {
        tbody.insertAdjacentHTML('beforeend', rowsHtml);
        ensureBackupSentinel();
    }
}

async function openBackupOriginLog(docId) {
    const tenantId = currentBackupTenantIdForDetail();
    const metaEl = document.getElementById('backupOriginLogMeta');
    const contentEl = document.getElementById('backupOriginLogContent');

    if (!tenantId) {
        contentEl.textContent = 'Không xác định được tổ chức để truy vấn.';
        metaEl.textContent = '';
    } else {
        contentEl.textContent = 'Đang tải...';
        metaEl.textContent = '';

        try {
            const url = `/monitor/api/tenant/${encodeURIComponent(tenantId)}/backup/${encodeURIComponent(docId)}/`;
            const res = await fetch(url);
            const data = await res.json();

            if (data.error) {
                contentEl.textContent = data.error;
            } else {
                contentEl.textContent = JSON.stringify(data, null, 2);
                const t = data.timestamp ? String(data.timestamp).replace('T', ' ').substring(0, 19) : '-';
                metaEl.innerHTML = `<strong>Tài khoản:</strong> ${escapeHtmlText(data.account || '-')}
                    &nbsp;|&nbsp; <strong>Thời gian:</strong> ${escapeHtmlText(t)}
                    &nbsp;|&nbsp; <strong>Document ID:</strong> <span class="font-monospace">${escapeHtmlText(docId)}</span>`;
            }
        } catch (e) {
            contentEl.textContent = 'Lỗi hệ thống, không thể tải nội dung log.';
        }
    }

    const modalEl = document.getElementById('modalBackupOriginLog');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
}

// ⭐ THÊM: Xuất Excel cho Backup
async function exportBackupToExcel() {
    if (!hasActiveBackupScope()) {
        alert('Vui lòng chọn Tổ chức (Tenant) trước khi xuất Excel.');
        return;
    }

    const btn = document.getElementById('btnExportBackupExcel');
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Đang xuất...';

    try {
        let url = API_EXPORT_BACKUP_URL + '?';

        const dateFrom = document.getElementById('backupDateFrom').value;
        const dateTo = document.getElementById('backupDateTo').value;
        const mode = document.getElementById('backupMode').value;
        const status = document.getElementById('backupStatus').value;
        const account = document.getElementById('backupSearchAccount').value;

        if (dateFrom) url += `date_from=${encodeURIComponent(dateFrom)}&`;
        if (dateTo) url += `date_to=${encodeURIComponent(dateTo)}&`;
        if (!dateFrom && !dateTo) url += 'hours=24&';
        if (mode) url += `backup_mode=${encodeURIComponent(mode)}&`;
        if (status) url += `status=${encodeURIComponent(status)}&`;
        if (account) url += `search_account=${encodeURIComponent(account)}&`;
        if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) {
            url += `tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}&`;
        }

        url = url.replace(/&$/, '');

        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);

        const blob = await response.blob();
        downloadBlob(blob, getDefaultFilename('backup_logs'));

    } catch (error) {
        alert(`Lỗi xuất Excel: ${error.message}`);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}

function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function getDefaultFilename(prefix) {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hour = String(now.getHours()).padStart(2, '0');
    const minute = String(now.getMinutes()).padStart(2, '0');
    return `${prefix}_${year}${month}${day}_${hour}${minute}.xlsx`;
}

async function loadBackupSummary() {
    if (!hasActiveBackupScope()) return;

    const queryStr = buildBackupQueryParams().replace(/&page=1&page_size=50/, '').replace(/page=1&page_size=50/, '');

    try {
        const response = await fetch(`/monitor/api/backup/summary/?${queryStr}`);
        const data = await response.json();

        if (!data.error) {
            document.getElementById('summary-unique-accounts').textContent = data.unique_accounts_backed_up || 0;
            document.getElementById('summary-total-size').textContent = formatFileSize(data.total_size_bytes || 0);
            document.getElementById('summary-failed').textContent = data.failed_count || 0;
            document.getElementById('summary-no-content').textContent = data.no_content_count || 0;
        }
    } catch (e) {
        // Nếu lỗi, để giá trị mặc định, không phá vỡ giao diện
    }
}

function formatFileSize(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function escapeHtmlText(str) { return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''; }
function escapeAttr(str) { return str ? String(str).replace(/'/g, "\\'") : ''; }