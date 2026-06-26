/**
 * monitor_mailbox.js
 * Logic trang Giám sát thư đi/đến (log-mailbox-*) -- dạng bảng, theo ĐÚNG
 * khuôn monitor_audit.js (KHÔNG có realtime WebSocket, vì đây là log tra
 * cứu lịch sử thư, không cần cập nhật liên tục từng giây).
 *
 * PHÂN TRANG: dạng "tải thêm khi kéo scroll" (infinite scroll) -- dùng
 * IntersectionObserver quan sát 1 dòng "sentinel" vô hình ở cuối bảng.
 * Khi dòng đó lọt vào viewport (người dùng kéo gần tới cuối bảng), tự
 * động gọi API lấy trang kế tiếp và NỐI (append) thêm dòng vào tbody --
 * KHÔNG xóa dữ liệu đã hiển thị trước đó (khác hẳn cách load cũ là xóa
 * toàn bộ rồi render lại mỗi lần submit filter).
 */

const API_MAILBOX_URL = '/monitor/api/mailbox/';

window.MONITOR_IS_SUPERUSER = window.MONITOR_IS_SUPERUSER || false;
window.MONITOR_TENANT_ID = null; // Superuser: chưa chọn gì khi tải trang lần đầu.
window.MONITOR_USER_TENANT_ID = window.MONITOR_USER_TENANT_ID || null;

const MAILBOX_PAGE_SIZE = 50;

// State phân trang -- reset về trang 1 + xóa dữ liệu cũ mỗi khi đổi filter
// (xem resetAndLoadMailbox()); tăng dần khi observer kích hoạt load thêm.
let mailboxCurrentPage = 1;
let mailboxTotalPages = 1;
let mailboxIsLoading = false;   // chặn gọi API trùng lặp khi observer bắn liên tục
let mailboxObserver = null;

function hasActiveScopeMailbox() {
    if (!window.MONITOR_IS_SUPERUSER) return true;
    return !!window.MONITOR_TENANT_ID;
}

/** Tenant dùng để build URL gọi API chi tiết (modal) -- giống audit. */
function currentTenantIdForMailboxDetail() {
    return window.MONITOR_IS_SUPERUSER ? window.MONITOR_TENANT_ID : window.MONITOR_USER_TENANT_ID;
}

document.addEventListener('DOMContentLoaded', () => {
    setupMailboxScrollObserver();

    if (hasActiveScopeMailbox()) {
        resetAndLoadMailbox();
    } else {
        renderSelectTenantPlaceholderMailbox();
    }

    const filterForm = document.getElementById('mailboxFilterForm');
    if (filterForm) {
        filterForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (hasActiveScopeMailbox()) resetAndLoadMailbox();
        });
    }

    const btnRefresh = document.getElementById('btnRefreshMailbox');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            if (hasActiveScopeMailbox()) resetAndLoadMailbox();
        });
    }

    const selectTenant = document.getElementById('selectMailboxTenant');
    if (selectTenant) {
        selectTenant.addEventListener('change', () => {
            window.MONITOR_TENANT_ID = selectTenant.value ? parseInt(selectTenant.value, 10) : null;
            if (hasActiveScopeMailbox()) {
                resetAndLoadMailbox();
            } else {
                renderSelectTenantPlaceholderMailbox();
            }
        });
    }
});

/**
 * Tạo 1 dòng "sentinel" (vô hình, cao 1px) ngay sau tbody, và 1
 * IntersectionObserver theo dõi dòng đó. Khi dòng lọt vào viewport (đang
 * cuộn gần tới cuối bảng), tự gọi loadMoreMailboxLogs() -- chỉ cần tạo
 * observer 1 LẦN DUY NHẤT khi trang load, không cần tạo lại mỗi lần fetch.
 */
function setupMailboxScrollObserver() {
    const tbody = document.getElementById('mailboxTableBody');
    if (!tbody) return;

    mailboxObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) loadMoreMailboxLogs();
        });
    }, { root: null, rootMargin: '0px 0px 200px 0px', threshold: 0 });
    // rootMargin 200px: bắt đầu tải SỚM hơn 200px trước khi sentinel thực
    // sự hiện ra, để người dùng kéo tới gần cuối là dữ liệu mới đã kịp có,
    // tránh cảm giác giật/khoảng trống chờ tải.
}

/** Đặt lại dòng sentinel ở cuối tbody và (re-)đăng ký observer theo dõi nó. */
function ensureMailboxSentinel() {
    const tbody = document.getElementById('mailboxTableBody');
    let sentinel = document.getElementById('mailboxScrollSentinel');
    if (sentinel) sentinel.remove();

    sentinel = document.createElement('tr');
    sentinel.id = 'mailboxScrollSentinel';
    sentinel.innerHTML = '<td colspan="8" style="height:1px;padding:0;border:0;"></td>';
    tbody.appendChild(sentinel);

    if (mailboxObserver) mailboxObserver.observe(sentinel);
}

/** Đổi filter (tenant/submit form/làm mới) -- xóa dữ liệu cũ, quay về trang 1, tải lại từ đầu. */
function resetAndLoadMailbox() {
    mailboxCurrentPage = 1;
    mailboxTotalPages = 1;
    const tbody = document.getElementById('mailboxTableBody');
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>Đang truy xuất dữ liệu thư...</td></tr>`;
    loadMailboxPage(true);
}

/** Observer gọi hàm này khi cuộn gần cuối bảng -- chỉ tải tiếp nếu còn trang và không đang tải. */
function loadMoreMailboxLogs() {
    if (mailboxIsLoading) return;
    if (mailboxCurrentPage >= mailboxTotalPages) return; // đã tải hết, không còn trang nào
    mailboxCurrentPage += 1;
    loadMailboxPage(false);
}

function renderSelectTenantPlaceholderMailbox() {
    const tbody = document.getElementById('mailboxTableBody');
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Vui lòng chọn Tổ chức (Tenant) để xem dữ liệu thư.</td></tr>`;
    const footer = document.getElementById('mailboxLoadFooter');
    if (footer) footer.innerHTML = '';
}

function buildMailboxQueryParams() {
    const rangeTypeEl = document.getElementById('mailboxRangeType');
    const rangeValueEl = document.getElementById('mailboxRangeValue');
    const directionEl = document.getElementById('mailboxDirection');
    const statusEl = document.getElementById('mailboxStatus');
    const searchEmailEl = document.getElementById('mailboxSearchEmail');

    const rangeType = rangeTypeEl ? rangeTypeEl.value : 'hours';
    let rangeValue = rangeValueEl ? rangeValueEl.value.trim() : '24';
    if (!rangeValue || isNaN(rangeValue)) rangeValue = '24';

    let params = `${rangeType}=${rangeValue}`;
    if (directionEl && directionEl.value) params += `&mail_direction=${encodeURIComponent(directionEl.value)}`;
    if (statusEl && statusEl.value) params += `&status=${encodeURIComponent(statusEl.value)}`;
    if (searchEmailEl && searchEmailEl.value.trim()) params += `&search_email=${encodeURIComponent(searchEmailEl.value.trim())}`;
    if (window.MONITOR_IS_SUPERUSER && window.MONITOR_TENANT_ID) params += `&tenant_id=${encodeURIComponent(window.MONITOR_TENANT_ID)}`;
    params += `&page=${mailboxCurrentPage}&page_size=${MAILBOX_PAGE_SIZE}`;
    return params;
}

/**
 * isFirstLoad=true: trang 1, tbody đang được XÓA SẠCH và render lại từ đầu.
 * isFirstLoad=false: trang kế tiếp do observer kích hoạt, NỐI thêm dòng
 * vào tbody hiện có, không xóa gì cả.
 */
async function loadMailboxPage(isFirstLoad) {
    mailboxIsLoading = true;
    renderMailboxLoadFooter('loading');

    const queryStr = buildMailboxQueryParams();
    try {
        const response = await fetch(`${API_MAILBOX_URL}?${queryStr}`);
        if (!response.ok) throw new Error(`Mã lỗi HTTP: ${response.status}`);
        const data = await response.json();

        mailboxTotalPages = data.total_pages || 1;
        appendMailboxRows(data.items || [], isFirstLoad);
        renderMailboxLoadFooter('idle', data.total || 0);
    } catch (error) {
        const tbody = document.getElementById('mailboxTableBody');
        if (isFirstLoad) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger py-4">${escapeHtmlTextMailbox(error.message || 'Lỗi truy vấn dữ liệu.')}</td></tr>`;
        }
        renderMailboxLoadFooter('error', 0, error.message);
        // Lùi lại page để lần kéo scroll tiếp theo có thể thử lại trang
        // vừa lỗi, không bị "kẹt" mãi ở trang đã tăng nhưng chưa tải được.
        if (!isFirstLoad) mailboxCurrentPage -= 1;
    } finally {
        mailboxIsLoading = false;
    }
}

/** Hiển thị trạng thái dưới bảng: đang tải / đã hết dữ liệu / lỗi -- KHÔNG dùng nút bấm, chỉ là chỉ báo trực quan cho infinite scroll. */
function renderMailboxLoadFooter(state, total, errorMessage) {
    let footer = document.getElementById('mailboxLoadFooter');
    if (!footer) {
        const tableCard = document.getElementById('mailboxTableBody').closest('.card');
        footer = document.createElement('div');
        footer.id = 'mailboxLoadFooter';
        footer.className = 'text-center text-muted small py-3';
        tableCard.insertAdjacentElement('afterend', footer);
    }

    if (state === 'loading') {
        footer.innerHTML = `<div class="spinner-border spinner-border-sm me-2"></div>Đang tải thêm...`;
    } else if (state === 'error') {
        footer.innerHTML = `<span class="text-danger">${escapeHtmlTextMailbox(errorMessage || 'Lỗi tải dữ liệu.')}</span>`;
    } else if (mailboxCurrentPage >= mailboxTotalPages) {
        footer.innerHTML = total > 0
            ? `Đã hiển thị tất cả ${total} bản ghi.`
            : '';
    } else {
        footer.innerHTML = `<small>Kéo xuống để tải thêm...</small>`;
    }
}

function directionBadgeMailbox(direction) {
    const map = {
        'INTERNAL': 'bg-secondary',
        'OUTBOUND': 'bg-primary',
        'INBOUND': 'bg-info text-dark',
        'EXTERNAL': 'bg-dark',
        'BOUNCE_SYSTEM': 'bg-danger',
    };
    const cls = map[direction] || 'bg-secondary';
    return `<span class="badge ${cls}">${escapeHtmlTextMailbox(direction || '-')}</span>`;
}

function statusBadgeMailbox(status) {
    if (status === 'sent') return '<span class="badge bg-success">Đã gửi</span>';
    if (status === 'deferred') return '<span class="badge bg-warning text-dark">Tạm hoãn</span>';
    if (status === 'bounced') return '<span class="badge bg-danger">Bị trả lại</span>';
    return '<span class="badge bg-secondary">-</span>';
}

/**
 * Convert chuỗi @timestamp UTC sang giờ Việt Nam (GMT+7) -- xem giải
 * thích chi tiết trong formatVNTimeAudit() của monitor_audit.js (cùng
 * cách làm, ÉP CỨNG timeZone 'Asia/Ho_Chi_Minh' không phụ thuộc timezone
 * máy người dùng).
 */
function formatVNTimeMailbox(utcTimestamp) {
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

function mailboxRowHtml(item) {
    const from = item.from || '-';
    const to = item.to || '-';
    const size = (item.size !== undefined && item.size !== null) ? `${item.size} B` : '-';
    const delay = (item.delay !== undefined && item.delay !== null) ? `${item.delay}s` : '-';
    const t = formatVNTimeMailbox(item['@timestamp']);

    return `
        <tr class="small" style="cursor:pointer" onclick="openMailboxOriginLog('${escapeAttrMailbox(item._id)}')">
            <td class="ps-3 text-muted font-monospace">${escapeHtmlTextMailbox(t)}</td>
            <td class="fw-semibold">${escapeHtmlTextMailbox(from)}</td>
            <td>${escapeHtmlTextMailbox(to)}</td>
            <td>${directionBadgeMailbox(item.mail_direction)}</td>
            <td>${statusBadgeMailbox(item.status)}</td>
            <td class="font-monospace text-muted">${size}</td>
            <td class="font-monospace text-muted">${delay}</td>
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
function appendMailboxRows(items, isFirstLoad) {
    const tbody = document.getElementById('mailboxTableBody');

    if (isFirstLoad) {
        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted py-4">Không có bản ghi nào thỏa mãn điều kiện lọc.</td></tr>`;
            // Vẫn cần sentinel để lần đổi filter sau (có dữ liệu) hoạt động bình thường.
            ensureMailboxSentinel();
            return;
        }
        tbody.innerHTML = items.map(mailboxRowHtml).join('');
        ensureMailboxSentinel();
        return;
    }

    if (items.length === 0) return;

    const sentinel = document.getElementById('mailboxScrollSentinel');
    const rowsHtml = items.map(mailboxRowHtml).join('');
    if (sentinel) {
        sentinel.insertAdjacentHTML('beforebegin', rowsHtml);
    } else {
        tbody.insertAdjacentHTML('beforeend', rowsHtml);
        ensureMailboxSentinel();
    }
}

/** Mở modal xem JSON đầy đủ của 1 document -- gọi API riêng theo tenant_id (path) + doc_id. */
async function openMailboxOriginLog(docId) {
    const tenantId = currentTenantIdForMailboxDetail();
    const metaEl = document.getElementById('mailboxOriginLogMeta');
    const contentEl = document.getElementById('mailboxOriginLogContent');

    if (!tenantId) {
        contentEl.textContent = 'Không xác định được tổ chức để truy vấn.';
        metaEl.textContent = '';
    } else {
        contentEl.textContent = 'Đang tải...';
        metaEl.textContent = '';

        try {
            const url = `/monitor/api/tenant/${encodeURIComponent(tenantId)}/mailbox/${encodeURIComponent(docId)}/`;
            const res = await fetch(url);
            const data = await res.json();

            if (data.error) {
                contentEl.textContent = data.error;
            } else {
                // Hiển thị TOÀN BỘ _source dạng JSON pretty-print (khác
                // audit vốn chỉ hiển thị field "message" nguyên văn) --
                // mailbox không có 1 field "message" gốc duy nhất, dữ liệu
                // đã được Logstash tách thành nhiều field riêng (from, to,
                // status, mail_direction...), nên xem JSON đầy đủ hữu ích
                // hơn cho việc tra cứu/debug.
                contentEl.textContent = JSON.stringify(data, null, 2);
                const t = formatVNTimeMailbox(data['@timestamp']);
                metaEl.innerHTML = `<strong>Queue ID:</strong> ${escapeHtmlTextMailbox(data.queue_id || '-')}
                    &nbsp;|&nbsp; <strong>Thời gian:</strong> ${escapeHtmlTextMailbox(t)}
                    &nbsp;|&nbsp; <strong>Document ID:</strong> <span class="font-monospace">${escapeHtmlTextMailbox(docId)}</span>`;
            }
        } catch (e) {
            contentEl.textContent = 'Lỗi hệ thống, không thể tải nội dung log.';
        }
    }

    const modalEl = document.getElementById('modalMailboxOriginLog');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
}

function escapeHtmlTextMailbox(str) { return str ? String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''; }
function escapeAttrMailbox(str) { return str ? String(str).replace(/'/g, "\\'") : ''; }