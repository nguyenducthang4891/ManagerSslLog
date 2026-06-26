/**
 * monitor_backup.js - VERSION 2
 * Logic trang Giám sát Backup Mailbox (log-backup-*)
 *
 * ⭐ THAY ĐỔI: Bỏ filter "giờ/ngày", thay vào dùng Date Picker (từ ngày - đến ngày)
 *
 * PHÂN TRANG: dạng "tải thêm khi kéo scroll" (infinite scroll) -- dùng
 * IntersectionObserver quan sát 1 dòng "sentinel" vô hình ở cuối bảng.
 */

const API_BACKUP_URL = '/monitor/api/backup/';
const API_BACKUP_SUMMARY_URL = '/monitor/api/backup/summary/';

window.MONITOR_IS_SUPERUSER = window.MONITOR_IS_SUPERUSER || false;
window.MONITOR_TENANT_ID = null;
window.MONITOR_USER_TENANT_ID = window.MONITOR_USER_TENANT_ID || null;

const BACKUP_PAGE_SIZE = 50;

let backupCurrentPage = 1;
let backupTotalPages = 1;
let backupIsLoading = false;
let backupObserver = null;

function hasActiveScopeBackup() {
    if (!window.MONITOR_IS_SUPERUSER) return true;
    return !!window.MONITOR_TENANT_ID;
}

function currentTenantIdForBackupDetail() {
    return window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;
}

document.addEventListener('DOMContentLoaded', () => {
    setupBackupScrollObserver();

    // ⭐ Set default dates (hôm nay)
    const today = new Date();
    const todayStr = today.toISOString().split('T')[0];
    document.getElementById('backupDateFrom').value = todayStr;
    document.getElementById('backupDateTo').value = todayStr;

    if (hasActiveScopeBackup()) {
        resetAndLoadBackup();
    } else {
        renderSelectTenantPlaceholderBackup();
    }

    const filterForm = document.getElementById('backupFilterForm');
    if (filterForm) {
        filterForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (hasActiveScopeBackup()) resetAndLoadBackup();
        });
    }

    const btnRefresh = document.getElementById('btnRefreshBackup');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            if (hasActiveScopeBackup()) resetAndLoadBackup();
        });
    }

    const selectTenant = document.getElementById('selectBackupTenant');
    if (selectTenant) {
        selectTenant.addEventListener('change', () => {
            window.MONITOR_TENANT_ID = selectTenant.value ? parseInt(selectTenant.value, 10) : null;
            if (hasActiveScopeBackup()) {
                resetAndLoadBackup();
            } else {
                renderSelectTenantPlaceholderBackup();
                renderBackupSummary(null);
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
    loadBackupSummary();
}

function loadMoreBackupLogs() {
    if (backupIsLoading) return;
    if (backupCurrentPage >= backupTotalPages) return;
    backupCurrentPage += 1;
    loadBackupPage(false);
}

function renderSelectTenantPlaceholderBackup() {
    const tbody = document.getElementById('backupTableBody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Vui lòng chọn Tổ chức (Tenant) để xem dữ liệu backup.</td></tr>`;
    const footer = document.getElementById('backupLoadFooter');
    if (footer) footer.innerHTML = '';
}

/**
 * ⭐ BUILD QUERY PARAMS - SỬA LẠI
 * Thay vì hours/days, giờ dùng dateFrom/dateTo (ISO format: YYYY-MM-DD)
 *
 * API sẽ nhận parameters: date_from, date_to, backup_mode
 * Backend sẽ convert sang Elasticsearch date range query
 */
function buildBackupQueryParamsBase() {
    const dateFromEl = document.getElementById('backupDateFrom');
    const dateToEl = document.getElementById('backupDateTo');
    const modeEl = document.getElementById('backupMode');

    const dateFrom = dateFromEl ? dateFromEl.value : '';
    const dateTo = dateToEl ? dateToEl.value : '';

    let params = '';
    if (dateFrom) params += `date_from=${encodeURIComponent(dateFrom)}`;
    if (dateTo) params += (params ? '&' : '') + `date_to=${encodeURIComponent(dateTo)}`;
    if (modeEl && modeEl.value) params += (params ? '&' : '') + `backup_mode=${encodeURIComponent(modeEl.value)}`;
    if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) params += (params ? '&' : '') + `tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}`;

    return params;
}

function buildBackupQueryParams() {
    const statusEl = document.getElementById('backupStatus');
    const searchAccountEl = document.getElementById('backupSearchAccount');

    let params = buildBackupQueryParamsBase();
    if (statusEl && statusEl.value) params += (params ? '&' : '') + `status=${encodeURIComponent(statusEl.value)}`;
    if (searchAccountEl && searchAccountEl.value.trim()) params += (params ? '&' : '') + `search_account=${encodeURIComponent(searchAccountEl.value.trim())}`;
    params += (params ? '&' : '') + `page=${backupCurrentPage}&page_size=${BACKUP_PAGE_SIZE}`;
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

        if (data.error) {
            renderBackupLoadFooter('error', null, data.error);
        } else {
            backupTotalPages = data.total_pages || 1;
            appendBackupRows(data.items || [], isFirstLoad);
            renderBackupLoadFooter(null, data.total);
        }
    } catch (e) {
        console.error('Error loading backup page:', e);
        renderBackupLoadFooter('error', null, e.message || 'Lỗi hệ thống');
    } finally {
        backupIsLoading = false;
    }
}

/**
 * ⭐ Gọi API thống kê tổng hợp
 * Kiểm tra scope trước khi gọi
 */
async function loadBackupSummary() {
    if (!hasActiveScopeBackup()) {
        renderBackupSummary(null);
        return;
    }

    const queryStr = buildBackupQueryParamsBase();
    console.log('Loading backup summary with params:', queryStr);

    try {
        const url = `${API_BACKUP_SUMMARY_URL}?${queryStr}`;
        const response = await fetch(url);

        if (!response.ok) {
            const errorText = await response.text();
            console.error(`API summary HTTP ${response.status}:`, errorText);
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        console.log('API summary response:', data);

        if (data.error) {
            console.error('API summary error:', data.error);
            renderBackupSummary(null);
        } else {
            renderBackupSummary(data);
        }
    } catch (e) {
        console.error('Error loading backup summary:', e);
        renderBackupSummary(null);
    }
}

function formatBytesBackup(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const num = bytes / Math.pow(k, i);
    return `${num.toFixed(1)} ${sizes[i]}`;
}

function renderBackupSummary(data) {
    const elAccounts = document.getElementById('summary-unique-accounts');
    const elSize = document.getElementById('summary-total-size');
    const elFailed = document.getElementById('summary-failed');
    const elNoContent = document.getElementById('summary-no-content');

    if (!data) {
        if (elAccounts) elAccounts.textContent = '0';
        if (elSize) elSize.textContent = '0 B';
        if (elFailed) elFailed.textContent = '0';
        if (elNoContent) elNoContent.textContent = '0';
        return;
    }

    if (elAccounts) elAccounts.textContent = data.unique_accounts_backed_up || 0;
    if (elSize) elSize.textContent = formatBytesBackup(data.total_size_bytes || 0);
    if (elFailed) elFailed.textContent = data.failed_count || 0;
    if (elNoContent) elNoContent.textContent = data.no_content_count || 0;
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
        footer.innerHTML = `<span class="text-danger">${escapeHtmlTextBackup(errorMessage || 'Lỗi tải dữ liệu.')}</span>`;
    } else if (backupCurrentPage >= backupTotalPages) {
        footer.innerHTML = total > 0
            ? `Đã hiển thị tất cả ${total} bản ghi.`
            : '';
    } else {
        footer.innerHTML = `<small>Kéo xuống để tải thêm...</small>`;
    }
}

function formatVNTimeBackup(utcTimestamp) {
    if (!utcTimestamp) return '-';
    const date = new Date(utcTimestamp);
    if (isNaN(date.getTime())) return '-';

    const formatter = new Intl.DateTimeFormat('vi-VN', {
        timeZone: 'Asia/Ho_Chi_Minh',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
    });
    const parts = formatter.formatToParts(date);
    const get = (type) => parts.find(p => p.type === type)?.value || '';
    return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`;
}

function modeBadgeBackup(mode) {
    if (mode === 'full') return '<span class="badge bg-primary">Full</span>';
    if (mode === 'inc') return '<span class="badge bg-info text-dark">Incremental</span>';
    return `<span class="badge bg-secondary">${escapeHtmlTextBackup(mode || '-')}</span>`;
}

function statusBadgeBackup(status) {
    if (status === 'SUCCESS') return '<span class="badge bg-success">Thành công</span>';
    if (status === 'FAILED') return '<span class="badge bg-danger">Thất bại</span>';
    if (status === 'NO_CONTENT') return '<span class="badge bg-secondary">Không có email mới</span>';
    return '<span class="badge bg-secondary">-</span>';
}

function backupRowHtml(item) {
    const account = item.account || '-';
    const size = item.size || '-';
    const duration = (item.duration !== undefined && item.duration !== null) ? `${item.duration}s` : '-';
    const t = formatVNTimeBackup(item['@timestamp']);

    return `
        <tr class="small" style="cursor:pointer" onclick="openBackupOriginLog('${escapeAttrBackup(item._id)}')">
            <td class="ps-3 text-muted font-monospace">${escapeHtmlTextBackup(t)}</td>
            <td class="fw-semibold">${escapeHtmlTextBackup(account)}</td>
            <td>${modeBadgeBackup(item.backup_mode)}</td>
            <td>${statusBadgeBackup(item.status)}</td>
            <td class="font-monospace text-muted">${escapeHtmlTextBackup(size)}</td>
            <td class="font-monospace text-muted">${duration}</td>
            <td class="text-end pe-3"><i class="bi bi-eye text-muted"></i></td>
        </tr>
    `;
}

function appendBackupRows(items, isFirstLoad) {
    const tbody = document.getElementById('backupTableBody');

    if (isFirstLoad) {
        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Không có bản ghi nào thỏa mãn điều kiện lọc.</td></tr>`;
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
    const tenantId = currentTenantIdForBackupDetail();
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
                const t = formatVNTimeBackup(data['@timestamp']);
                metaEl.innerHTML = `<strong>Tài khoản:</strong> ${escapeHtmlTextBackup(data.account || '-')}
                    &nbsp;|&nbsp; <strong>Thời gian:</strong> ${escapeHtmlTextBackup(t)}
                    &nbsp;|&nbsp; <strong>Document ID:</strong> <span class="font-monospace">${escapeHtmlTextBackup(docId)}</span>`;
            }
        } catch (e) {
            contentEl.textContent = 'Lỗi hệ thống, không thể tải nội dung log.';
        }
    }

    const modalEl = document.getElementById('modalBackupOriginLog');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
}

function escapeHtmlTextBackup(str) { return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''; }
function escapeAttrBackup(str) { return str ? String(str).replace(/'/g, "\\'") : ''; }