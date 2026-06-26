/**
 * monitor_backup.js
 * Logic trang Giám sát Backup Mailbox (log-backup-*) -- dạng bảng, theo
 * ĐÚNG khuôn monitor_mailbox.js (KHÔNG có realtime WebSocket, vì đây là
 * log tra cứu lịch sử backup, không cần cập nhật liên tục từng giây).
 *
 * PHÂN TRANG: dạng "tải thêm khi kéo scroll" (infinite scroll) -- dùng
 * IntersectionObserver quan sát 1 dòng "sentinel" vô hình ở cuối bảng,
 * giống monitor_mailbox.js/monitor_audit.js.
 *
 * THÊM RIÊNG (khác mailbox): loadBackupSummary() -- gọi API thống kê
 * tổng hợp (api_backup_summary) CHẠY SONG SONG với loadBackupPage() mỗi
 * khi đổi filter/tenant, để cập nhật 4 thẻ số liệu phía trên bảng (số tài
 * khoản đã backup, tổng dung lượng, số thất bại, số không có email mới)
 * -- đúng mục đích ban đầu (thống kê theo ngày).
 */

const API_BACKUP_URL = '/monitor/api/backup/';
const API_BACKUP_SUMMARY_URL = '/monitor/api/backup/summary/';

window.MONITOR_IS_SUPERUSER = window.MONITOR_IS_SUPERUSER || false;
window.MONITOR_TENANT_ID = null; // Superuser: chưa chọn gì khi tải trang lần đầu.
window.MONITOR_USER_TENANT_ID = window.MONITOR_USER_TENANT_ID || null;

const BACKUP_PAGE_SIZE = 50;

// State phân trang -- reset về trang 1 + xóa dữ liệu cũ mỗi khi đổi filter
// (xem resetAndLoadBackup()); tăng dần khi observer kích hoạt load thêm.
let backupCurrentPage = 1;
let backupTotalPages = 1;
let backupIsLoading = false;   // chặn gọi API trùng lặp khi observer bắn liên tục
let backupObserver = null;

function hasActiveScopeBackup() {
    if (!window.MONITOR_IS_SUPERUSER) return true;
    return !!window.MONITOR_TENANT_ID;
}

/** Tenant dùng để build URL gọi API chi tiết (modal) -- giống mailbox/audit. */
function currentTenantIdForBackupDetail() {
    return window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;
}

document.addEventListener('DOMContentLoaded', () => {
    setupBackupScrollObserver();

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
                renderBackupSummary(null); // Chưa chọn tenant -- xóa số liệu thẻ thống kê về 0.
            }
        });
    }
});

/**
 * Tạo 1 dòng "sentinel" (vô hình, cao 1px) ngay sau tbody, và 1
 * IntersectionObserver theo dõi dòng đó -- giống setupMailboxScrollObserver().
 */
function setupBackupScrollObserver() {
    const tbody = document.getElementById('backupTableBody');
    if (!tbody) return;

    backupObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) loadMoreBackupLogs();
        });
    }, { root: null, rootMargin: '0px 0px 200px 0px', threshold: 0 });
}

/** Đặt lại dòng sentinel ở cuối tbody và (re-)đăng ký observer theo dõi nó. */
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

/**
 * Đổi filter (tenant/submit form/làm mới) -- xóa dữ liệu cũ, quay về
 * trang 1, tải lại từ đầu. Gọi ĐỒNG THỜI loadBackupPage() (bảng chi
 * tiết) và loadBackupSummary() (4 thẻ thống kê) -- 2 API độc lập, không
 * cái nào chặn cái nào.
 */
function resetAndLoadBackup() {
    backupCurrentPage = 1;
    backupTotalPages = 1;
    const tbody = document.getElementById('backupTableBody');
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>Đang truy xuất dữ liệu backup...</td></tr>`;
    loadBackupPage(true);
    loadBackupSummary();
}

/** Observer gọi hàm này khi cuộn gần cuối bảng -- chỉ tải tiếp nếu còn trang và không đang tải. */
function loadMoreBackupLogs() {
    if (backupIsLoading) return;
    if (backupCurrentPage >= backupTotalPages) return; // đã tải hết, không còn trang nào
    backupCurrentPage += 1;
    loadBackupPage(false);
}

function renderSelectTenantPlaceholderBackup() {
    const tbody = document.getElementById('backupTableBody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4">Vui lòng chọn Tổ chức (Tenant) để xem dữ liệu backup.</td></tr>`;
    const footer = document.getElementById('backupLoadFooter');
    if (footer) footer.innerHTML = '';
}

/** Build query params DÙNG CHUNG cho cả loadBackupPage() và loadBackupSummary() -- cùng 1 bộ filter (thời gian + loại backup + tenant). */
function buildBackupQueryParamsBase() {
    const rangeTypeEl = document.getElementById('backupRangeType');
    const rangeValueEl = document.getElementById('backupRangeValue');
    const modeEl = document.getElementById('backupMode');

    const rangeType = rangeTypeEl ? rangeTypeEl.value : 'days';
    let rangeValue = rangeValueEl ? rangeValueEl.value.trim() : '1';
    if (!rangeValue || isNaN(rangeValue)) rangeValue = '1';

    let params = `${rangeType}=${rangeValue}`;
    if (modeEl && modeEl.value) params += `&backup_mode=${encodeURIComponent(modeEl.value)}`;
    if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) params += `&tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}`;
    return params;
}

function buildBackupQueryParams() {
    const statusEl = document.getElementById('backupStatus');
    const searchAccountEl = document.getElementById('backupSearchAccount');

    let params = buildBackupQueryParamsBase();
    if (statusEl && statusEl.value) params += `&status=${encodeURIComponent(statusEl.value)}`;
    if (searchAccountEl && searchAccountEl.value.trim()) params += `&search_account=${encodeURIComponent(searchAccountEl.value.trim())}`;
    params += `&page=${backupCurrentPage}&page_size=${BACKUP_PAGE_SIZE}`;
    return params;
}

/**
 * isFirstLoad=true: trang 1, tbody đang được XÓA SẠCH và render lại từ đầu.
 * isFirstLoad=false: trang kế tiếp do observer kích hoạt, NỐI thêm dòng
 * vào tbody hiện có, không xóa gì cả.
 */
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
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger py-4">${escapeHtmlTextBackup(error.message || 'Lỗi truy vấn dữ liệu.')}</td></tr>`;
        }
        renderBackupLoadFooter('error', 0, error.message);
        // Lùi lại page để lần kéo scroll tiếp theo có thể thử lại trang
        // vừa lỗi, không bị "kẹt" mãi ở trang đã tăng nhưng chưa tải được.
        if (!isFirstLoad) backupCurrentPage -= 1;
    } finally {
        backupIsLoading = false;
    }
}

/**
 * Gọi api_backup_summary -- ĐỘC LẬP với loadBackupPage(), dùng CHUNG bộ
 * filter thời gian/loại backup/tenant (KHÔNG áp status/search_account, vì
 * 4 thẻ thống kê luôn thể hiện TOÀN CẢNH của khoảng thời gian đã chọn,
 * không bị bó hẹp theo riêng status/account đang lọc trên bảng chi tiết
 * -- tránh gây hiểu lầm "tổng dung lượng" chỉ tính trên kết quả đang lọc).
 */
async function loadBackupSummary() {
    const queryStr = buildBackupQueryParamsBase();
    try {
        const response = await fetch(`${API_BACKUP_SUMMARY_URL}?${queryStr}`);
        if (!response.ok) throw new Error(`Mã lỗi HTTP: ${response.status}`);
        const data = await response.json();
        renderBackupSummary(data);
    } catch (error) {
        renderBackupSummary(null);
    }
}

/** Định dạng số bytes thành chuỗi dễ đọc (KB/MB/GB) -- giống cách hiển thị "size" trong log gốc. */
function formatBytesBackup(bytes) {
    if (bytes === undefined || bytes === null || isNaN(bytes)) return '0 B';
    const num = Number(bytes);
    if (num >= 1024 ** 3) return `${(num / 1024 ** 3).toFixed(2)} GB`;
    if (num >= 1024 ** 2) return `${(num / 1024 ** 2).toFixed(2)} MB`;
    if (num >= 1024) return `${(num / 1024).toFixed(2)} KB`;
    return `${num} B`;
}

/** data=null -- chưa có scope/lỗi tải, đưa 4 thẻ về trạng thái rỗng (0). */
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

/** Hiển thị trạng thái dưới bảng: đang tải / đã hết dữ liệu / lỗi -- KHÔNG dùng nút bấm, chỉ là chỉ báo trực quan cho infinite scroll. */
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

/**
 * Convert chuỗi @timestamp UTC (vd "2026-06-26T03:14:27.000Z") sang giờ
 * Việt Nam (GMT+7) để hiển thị trên UI -- log gốc luôn lưu UTC (chuẩn ES/
 * Logstash), nhưng người dùng xem ở VN nên hiển thị phải +7 giờ, KHÔNG
 * hiển thị thẳng chuỗi UTC thô như cách cũ (gây lệch 7 tiếng so với giờ
 * thực tế).
 */
function formatVNTimeBackup(utcTimestamp) {
    if (!utcTimestamp) return '-';
    const date = new Date(utcTimestamp); // JS tự parse đúng UTC nếu chuỗi có "Z" ở cuối
    if (isNaN(date.getTime())) return '-';

    // Dùng Intl với timeZone 'Asia/Ho_Chi_Minh' -- tự xử lý đúng GMT+7,
    // không cộng tay 7*3600*1000 (cách cộng tay dễ sai nếu server/browser
    // đổi giờ hệ thống, và không tự thích ứng nếu sau này đổi sang locale khác).
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

/**
 * isFirstLoad=true: xóa sạch tbody (kể cả dòng "Đang tải..." ban đầu) rồi
 * render items từ đầu. isFirstLoad=false: giữ nguyên dòng đã có, CHÈN
 * thêm dòng mới vào TRƯỚC dòng sentinel (luôn phải nằm cuối cùng để
 * observer tiếp tục theo dõi đúng vị trí).
 */
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

/** Mở modal xem JSON đầy đủ của 1 document -- gọi API riêng theo tenant_id (path) + doc_id. */
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
                // Hiển thị TOÀN BỘ _source dạng JSON pretty-print -- giống
                // cách mailbox xử lý (không có 1 field "message" gốc duy
                // nhất, dữ liệu đã ở dạng nhiều field riêng từ Filebeat
                // json.keys_under_root).
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