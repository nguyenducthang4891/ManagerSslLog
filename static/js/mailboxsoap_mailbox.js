/**
 * mailbox.js
 *
 * Logic toàn bộ tính năng "Tìm kiếm & Quản lý Email" (Mailbox Search):
 * - Tìm kiếm account theo email trong 1 domain
 * - Hiển thị chi tiết tài khoản
 * - Sửa hồ sơ (givenName, sn, displayName, title, mobile)
 * - Đặt lại mật khẩu (mọi vai trò)
 * - Đổi tên email (rename) - Superuser/Tenant Admin
 * - Đổi trạng thái (active/locked/closed) - Superuser/Tenant Admin
 * - Xóa vĩnh viễn account - Superuser/Tenant Admin
 * - Tải backup .tgz - Superuser/Tenant Admin
 */

document.addEventListener('DOMContentLoaded', function () {
    attachFormSearchHandlers();
    attachEditModalHandlers();
    attachResetPasswordModalHandlers();
    restoreSearchStateFromUrl();


});



// ============================================================================
// 1. FORM TÌM KIẾM (có Infinite Scroll)
// ============================================================================

// State của lần tìm kiếm hiện tại -- dùng để: (1) infinite scroll biết offset
// kế tiếp, (2) refresh lại đúng kết quả sau khi sửa tài khoản trong modal mà
// không cần location.reload() (tránh mất domain/từ khóa đang xem).
const mailboxSearchState = {
    domainId: null,
    query: '',
    offset: 0,
    isLoading: false,
    hasMore: false,
};

let mailboxScrollObserver = null;

function attachFormSearchHandlers() {
    const form = document.getElementById('mailboxSearchForm');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await performSearch({resetUrl: true});
    });
}

/**
 * Đọc domain_id/q từ URL query string lúc tải trang (nếu có) để tự điền lại
 * form và tìm kiếm ngay -- dùng khi quay lại trang sau khi lưu thay đổi trong
 * modal, hoặc khi người dùng chia sẻ/bookmark URL có sẵn kết quả tìm kiếm.
 */
function restoreSearchStateFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const domainId = params.get('domain_id');
    const query = params.get('q');

    if (!domainId || !query) return;

    const domainSelect = document.getElementById('domainSelect');
    const queryInput = document.getElementById('emailQueryInput');
    if (!domainSelect || !queryInput) return;

    // Chỉ set nếu domain đó thực sự có trong danh sách quyền của user hiện tại
    const optionExists = Array.from(domainSelect.options).some(opt => opt.value === domainId);
    if (!optionExists) return;

    domainSelect.value = domainId;
    queryInput.value = query;

    performSearch({resetUrl: false});
}

/**
 * Cập nhật URL (?domain_id=&q=) bằng replaceState, KHÔNG tạo entry lịch sử
 * mới và KHÔNG reload trang -- chỉ để giữ lại state khi người dùng F5 hoặc
 * khi mình chủ động re-search sau khi sửa tài khoản.
 */
function updateSearchUrl(domainId, query) {
    const url = new URL(window.location.href);
    url.searchParams.set('domain_id', domainId);
    url.searchParams.set('q', query);
    history.replaceState(null, '', url);
}

/**
 * Thực hiện tìm kiếm từ đầu (offset = 0), xóa bảng kết quả cũ.
 * @param {object} opts - { resetUrl: boolean } - true khi user bấm nút Tìm kiếm,
 *   false khi gọi lại để khôi phục/refresh state đã có (không cần update URL lại).
 */
async function performSearch(opts = {}) {
    const domainId = document.getElementById('domainSelect')?.value;
    const query = document.getElementById('emailQueryInput')?.value || '';

    if (!domainId) {
        showToast('Vui lòng chọn tên miền cần tìm kiếm.', 'warning');
        return;
    }

    if (!query.trim()) {
        showToast('Vui lòng nhập từ khóa email cần tìm kiếm.', 'warning');
        return;
    }

    // Reset state cho lần tìm kiếm mới
    mailboxSearchState.domainId = domainId;
    mailboxSearchState.query = query;
    mailboxSearchState.offset = 0;
    mailboxSearchState.hasMore = false;

    if (opts.resetUrl !== false) {
        updateSearchUrl(domainId, query);
    }

    const tbody = document.getElementById('mailboxResultsBody');
    if (tbody) tbody.innerHTML = '';
    removeScrollSentinel();

    setTableState('loading');
    await loadNextSearchPage({isFirstPage: true});
}

/**
 * Tải 1 "trang" kết quả kế tiếp dựa trên mailboxSearchState.offset hiện tại,
 * rồi nối thêm vào bảng (infinite scroll). Tự chặn gọi trùng nếu đang loading
 * hoặc đã hết dữ liệu.
 */
async function loadNextSearchPage(opts = {}) {
    const {isFirstPage = false} = opts;
    const state = mailboxSearchState;

    if (state.isLoading) return;
    if (!isFirstPage && !state.hasMore) return;

    state.isLoading = true;
    if (!isFirstPage) showScrollLoadingIndicator(true);

    try {
        const url = `/soap/api/mailbox/search/?domain_id=${state.domainId}` +
            `&q=${encodeURIComponent(state.query)}&offset=${state.offset}`;
        const result = await fetchJSON(url);

        if (!result.ok) {
            showToast(result.data.error || 'Lỗi truy vấn Zimbra.', 'danger');
            if (isFirstPage) setTableState('empty');
            state.hasMore = false;
            return;
        }

        const results = result.data.results || [];
        state.hasMore = !!result.data.has_more;

        if (isFirstPage && results.length === 0) {
            setTableState('empty');
            return;
        }

        appendSearchResults(results, state.domainId);
        setTableState('results');
        state.offset += results.length;

        if (state.hasMore) {
            ensureScrollSentinel();
        } else {
            removeScrollSentinel();
        }

    } catch (err) {
        console.error('Search error:', err);
        showToast('Lỗi kết nối. Vui lòng thử lại.', 'danger');
        if (isFirstPage) setTableState('empty');
        state.hasMore = false;
    } finally {
        state.isLoading = false;
        showScrollLoadingIndicator(false);
    }
}

function setTableState(state) {
    const loading = document.getElementById('mailboxLoading');
    const empty = document.getElementById('mailboxEmptyState');
    const table = document.getElementById('mailboxResultsTable');

    // Ẩn tất cả
    if (loading) loading.classList.add('d-none');
    if (empty) empty.classList.add('d-none');
    if (table) table.classList.add('d-none');

    // Hiện cái cần
    if (state === 'loading' && loading) {
        loading.classList.remove('d-none');
    } else if (state === 'empty' && empty) {
        empty.classList.remove('d-none');
    } else if (state === 'results' && table) {
        table.classList.remove('d-none');
    }
}

/**
 * Tạo (nếu chưa có) 1 hàng "sentinel" vô hình cuối bảng + IntersectionObserver
 * theo dõi nó. Khi sentinel lọt vào viewport (người dùng kéo tới đáy bảng),
 * tự động gọi loadNextSearchPage() để tải tiếp -- đây là cơ chế infinite scroll.
 */
function ensureScrollSentinel() {
    const tbody = document.getElementById('mailboxResultsBody');
    if (!tbody) return;

    let sentinelRow = document.getElementById('mailboxScrollSentinel');
    if (!sentinelRow) {
        sentinelRow = document.createElement('tr');
        sentinelRow.id = 'mailboxScrollSentinel';
        sentinelRow.innerHTML = `
            <td colspan="8" class="text-center text-muted py-3">
                <div class="spinner-border spinner-border-sm d-none" id="mailboxScrollSpinner"></div>
            </td>
        `;
        tbody.appendChild(sentinelRow);
    } else {
        // Đảm bảo sentinel luôn ở cuối cùng sau khi nối thêm kết quả mới
        tbody.appendChild(sentinelRow);
    }

    if (!mailboxScrollObserver) {
        mailboxScrollObserver = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    loadNextSearchPage();
                }
            });
        }, {root: null, rootMargin: '0px 0px 200px 0px', threshold: 0});
    }

    mailboxScrollObserver.observe(sentinelRow);
}

function removeScrollSentinel() {
    const sentinelRow = document.getElementById('mailboxScrollSentinel');
    if (sentinelRow) {
        if (mailboxScrollObserver) mailboxScrollObserver.unobserve(sentinelRow);
        sentinelRow.remove();
    }
}

function showScrollLoadingIndicator(show) {
    const spinner = document.getElementById('mailboxScrollSpinner');
    if (spinner) spinner.classList.toggle('d-none', !show);
}

/**
 * Nối thêm kết quả mới vào CUỐI bảng hiện có (không xóa kết quả cũ) --
 * dùng cho infinite scroll. displaySearchResults() (tên cũ) đã đổi thành
 * appendSearchResults() để phản ánh đúng hành vi "nối thêm".
 */
function appendSearchResults(results, domainId) {
    const tbody = document.getElementById('mailboxResultsBody');
    if (!tbody) return;

    results.forEach((account) => {
        const row = document.createElement('tr');

        // Render status badge
        const statusClass = `status-badge-${account.status || 'active'}`;
        const statusLabel = {
            'active': 'Hoạt động',
            'locked': 'Khóa',
            'closed': 'Đóng'
        }[account.status] || account.status;

        row.innerHTML = `
            <td class="fw-bold">${escapeHtml(account.email)}</td>
            <td>${escapeHtml(account.sn || '')}</td>
            <td>${escapeHtml(account.givenName || '')}</td>
            <td>${escapeHtml(account.displayName || '')}</td>
            <td>${escapeHtml(account.title || '')}</td>
            <td>${escapeHtml(account.mobile || '')}</td>
            <td>
                <span class="badge ${statusClass}">${statusLabel}</span>
            </td>
            <td class="text-end">
                <div class="btn-group btn-group-sm" role="group">
                    <button type="button" class="btn btn-outline-primary btn-action-reset-pwd"
                            data-domain-id="${domainId}" data-email="${escapeHtml(account.email)}">
                        <i class="bi bi-key"></i> Mật khẩu
                    </button>
                    ${window.MAILBOX_CAN_MANAGE ? `
                        <button type="button" class="btn btn-outline-secondary btn-action-edit"
                                data-domain-id="${domainId}" data-email="${escapeHtml(account.email)}">
                            <i class="bi bi-pencil"></i> Sửa
                        </button>
                        <button type="button" class="btn btn-outline-info btn-action-backup"
                                data-domain-id="${domainId}" data-email="${escapeHtml(account.email)}">
                            <i class="bi bi-download"></i> Backup
                        </button>
                    ` : ''}
                </div>
            </td>
        `;

        // Attach event handlers
        const btnResetPwd = row.querySelector('.btn-action-reset-pwd');
        if (btnResetPwd) {
            btnResetPwd.addEventListener('click', () => openResetPasswordModal(
                domainId,
                account.email
            ));
        }

        if (window.MAILBOX_CAN_MANAGE) {
            const btnEdit = row.querySelector('.btn-action-edit');
            if (btnEdit) {
                btnEdit.addEventListener('click', () => openEditModal(domainId, account.email));
            }

            const btnBackup = row.querySelector('.btn-action-backup');
            if (btnBackup) {
                btnBackup.addEventListener('click', () => downloadBackup(domainId, account.email, btnBackup));
            }
        }

        // Chèn TRƯỚC sentinel (nếu sentinel đã tồn tại từ trang trước), để
        // sentinel luôn nằm cuối cùng trong bảng.
        const sentinelRow = document.getElementById('mailboxScrollSentinel');
        if (sentinelRow) {
            tbody.insertBefore(row, sentinelRow);
        } else {
            tbody.appendChild(row);
        }
    });
}

// ============================================================================
// 2. MODAL: EDIT ACCOUNT (Sửa hồ sơ, Đổi tên, Đổi trạng thái, Xóa)
// ============================================================================

function attachEditModalHandlers() {
    const btnSave = document.getElementById('btnSaveAccountChanges');
    const btnDelete = document.getElementById('btnDeleteAccountInModal');

    if (btnSave) {
        btnSave.addEventListener('click', async (e) => {
            await saveAccountChanges(e);
        });
    }

    if (btnDelete) {
        btnDelete.addEventListener('click', async (e) => {
            await deleteAccount(e);
        });
    }
}

async function openEditModal(domainId, email) {
    // Fetch chi tiết account
    try {
        const result = await fetchJSON(`/soap/api/mailbox/detail/?domain_id=${domainId}&email=${encodeURIComponent(email)}`);

        if (!result.ok) {
            showToast(result.data.error || 'Không thể lấy chi tiết tài khoản.', 'danger');
            return;
        }

        const detail = result.data.detail || {};

        // Điền dữ liệu vào form
        document.getElementById('editDomainId').value = domainId;
        document.getElementById('editOriginalEmail').value = email;
        document.getElementById('editEmailDisplay').value = email;
        document.getElementById('editGivenName').value = detail.givenName || '';
        document.getElementById('editSn').value = detail.sn || '';
        document.getElementById('editDisplayName').value = detail.displayName || '';
        document.getElementById('editTitle').value = detail.title || '';
        document.getElementById('editMobile').value = detail.mobile || '';
        document.getElementById('editStatus').value = detail.status || 'active';
        document.getElementById('editNewEmail').value = '';

        toggleModal('editAccountModal', true);

    } catch (err) {
        console.error('Error opening edit modal:', err);
        showToast('Lỗi khi mở dialog chỉnh sửa.', 'danger');
    }
}

async function saveAccountChanges(event) {
    const domainId = parseInt(document.getElementById('editDomainId').value);
    const originalEmail = document.getElementById('editOriginalEmail').value;
    const newEmail = document.getElementById('editNewEmail').value.trim();
    const newStatus = document.getElementById('editStatus').value;

    // Chuẩn bị dữ liệu profile
    const profileData = new FormData();
    profileData.append('domain_id', domainId);
    profileData.append('email', originalEmail);
    profileData.append('givenName', document.getElementById('editGivenName').value);
    profileData.append('sn', document.getElementById('editSn').value);
    profileData.append('displayName', document.getElementById('editDisplayName').value);
    profileData.append('title', document.getElementById('editTitle').value);
    profileData.append('mobile', document.getElementById('editMobile').value);

    const requests = [];

    // 1. Update profile
    requests.push(
        fetchJSON('/soap/api/mailbox/update-profile/', {
            method: 'POST',
            body: profileData
        })
    );

    // 2. Rename nếu có email mới
    if (newEmail && newEmail !== originalEmail) {
        const renameData = new FormData();
        renameData.append('domain_id', domainId);
        renameData.append('email', originalEmail);
        renameData.append('new_email', newEmail);

        requests.push(
            fetchJSON('/soap/api/mailbox/rename/', {
                method: 'POST',
                body: renameData
            })
        );
    }

    // 3. Set status
    const statusData = new FormData();
    statusData.append('domain_id', domainId);
    statusData.append('email', newEmail && newEmail !== originalEmail ? newEmail : originalEmail);
    statusData.append('status', newStatus);

    requests.push(
        fetchJSON('/soap/api/mailbox/set-status/', {
            method: 'POST',
            body: statusData
        })
    );

    // Gửi tất cả request
    const btnSave = document.getElementById('btnSaveAccountChanges');
    if (btnSave) {
        btnSave.disabled = true;
        btnSave.classList.add('disabled');
    }

    try {
        const results = await Promise.all(requests);

        // Kiểm tra kết quả
        let hasError = false;
        for (const result of results) {
            if (!result.ok) {
                hasError = true;
                showToast(result.data.error || 'Lỗi khi cập nhật.', 'danger');
                break;
            }
        }

        if (!hasError) {
            showToast('Đã lưu thay đổi thành công!', 'success');
            toggleModal('editAccountModal', false);
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.classList.remove('disabled');
            }
            // Refresh lại đúng domain/từ khóa đang tìm kiếm (không reload cả
            // trang) -- vừa giữ được state tìm kiếm, vừa không "nuốt" toast.
            await performSearch({resetUrl: false});
        } else {
            if (btnSave) {
                btnSave.disabled = false;
                btnSave.classList.remove('disabled');
            }
        }

    } catch (err) {
        console.error('Error saving changes:', err);
        showToast('Lỗi kết nối. Vui lòng thử lại.', 'danger');
        if (btnSave) {
            btnSave.disabled = false;
            btnSave.classList.remove('disabled');
        }
    }
}

async function deleteAccount(event) {
    const domainId = parseInt(document.getElementById('editDomainId').value);
    const email = document.getElementById('editOriginalEmail').value;

    if (!confirm(`⚠️ CẢNH BÁO: Bạn sắp xóa vĩnh viễn tài khoản "${email}"!\n\nThao tác này KHÔNG thể hoàn tác. Bạn chắc chứ?`)) {
        return;
    }

    const formData = new FormData();
    formData.append('domain_id', domainId);
    formData.append('email', email);

    const btnDelete = document.getElementById('btnDeleteAccountInModal');
    if (btnDelete) {
        btnDelete.disabled = true;
        btnDelete.classList.add('disabled');
    }

    try {
        const result = await fetchJSON('/soap/api/mailbox/delete/', {
            method: 'POST',
            body: formData
        });

        if (result.ok) {
            showToast('Tài khoản đã xóa vĩnh viễn.', 'success');
            toggleModal('editAccountModal', false);
            if (btnDelete) {
                btnDelete.disabled = false;
                btnDelete.classList.remove('disabled');
            }
            // Refresh lại đúng domain/từ khóa đang tìm kiếm (không reload cả trang)
            await performSearch({resetUrl: false});
        } else {
            showToast(result.data.error || 'Lỗi xóa tài khoản.', 'danger');
            if (btnDelete) {
                btnDelete.disabled = false;
                btnDelete.classList.remove('disabled');
            }
        }

    } catch (err) {
        console.error('Error deleting account:', err);
        showToast('Lỗi kết nối. Vui lòng thử lại.', 'danger');
        if (btnDelete) {
            btnDelete.disabled = false;
            btnDelete.classList.remove('disabled');
        }
    }
}

// ============================================================================
// 3. MODAL: RESET PASSWORD
// ============================================================================

function attachResetPasswordModalHandlers() {
    const btnConfirm = document.getElementById('btnConfirmResetPassword');
    if (btnConfirm) {
        btnConfirm.addEventListener('click', async (e) => {
            await resetPassword(e);
        });
    }
    const toggleBtn = document.getElementById('togglePassword');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', function () {
            const passwordInput = document.getElementById('resetNewPassword');
            const toggleIcon = document.getElementById('toggleIcon');
            if (!passwordInput || !toggleIcon) return;

            if (passwordInput.type === 'password') {
                passwordInput.type = 'text';
                toggleIcon.classList.remove('bi-eye-slash');
                toggleIcon.classList.add('bi-eye');
            } else {
                passwordInput.type = 'password';
                toggleIcon.classList.remove('bi-eye');
                toggleIcon.classList.add('bi-eye-slash');
            }
        });
    }
}

function openResetPasswordModal(domainId, email) {
    document.getElementById('resetDomainId').value = domainId;
    document.getElementById('resetEmail').value = email;
    document.getElementById('resetEmailDisplay').textContent = email;
    document.getElementById('resetNewPassword').value = '';

    toggleModal('resetPasswordModal', true);
}

async function resetPassword(event) {
    const domainId = parseInt(document.getElementById('resetDomainId').value);
    const email = document.getElementById('resetEmail').value;
    const newPassword = document.getElementById('resetNewPassword').value;

    if (!newPassword || newPassword.length < 8) {
        showToast('Mật khẩu mới phải có ít nhất 8 ký tự.', 'warning');
        return;
    }

    const formData = new FormData();
    formData.append('domain_id', domainId);
    formData.append('email', email);
    formData.append('new_password', newPassword);

    const btnConfirm = document.getElementById('btnConfirmResetPassword');
    if (btnConfirm) {
        btnConfirm.disabled = true;
        btnConfirm.classList.add('disabled');
    }

    try {
        const result = await fetchJSON('/soap/api/mailbox/reset-password/', {
            method: 'POST',
            body: formData
        });

        if (result.ok) {
            showToast('Mật khẩu đã được đặt lại thành công!', 'success');
            setTimeout(() => {
                toggleModal('resetPasswordModal', false);
            }, 700);
        } else {
            showToast(result.data.error || 'Lỗi đặt lại mật khẩu.', 'danger');
            if (btnConfirm) {
                btnConfirm.disabled = false;
                btnConfirm.classList.remove('disabled');
            }
        }

    } catch (err) {
        console.error('Error resetting password:', err);
        showToast('Lỗi kết nối. Vui lòng thử lại.', 'danger');
        if (btnConfirm) {
            btnConfirm.disabled = false;
            btnConfirm.classList.remove('disabled');
        }
    }
}

// ============================================================================
// 4. BACKUP - Tải file backup .tgz
// ============================================================================

async function downloadBackup(domainId, email, btnElement) {
    if (!confirm(`Tải backup cho ${email}?\n\nFile có thể lớn và mất thời gian.`)) {
        return;
    }

    if (btnElement) {
        btnElement.disabled = true;
        btnElement.classList.add('disabled');
    }

    try {
        // Dùng form submit để tải file (thay vì fetch + blob)
        const form = document.createElement('form');
        form.method = 'GET';
        form.action = '/soap/api/mailbox/backup/';

        const inputDomain = document.createElement('input');
        inputDomain.type = 'hidden';
        inputDomain.name = 'domain_id';
        inputDomain.value = domainId;

        const inputEmail = document.createElement('input');
        inputEmail.type = 'hidden';
        inputEmail.name = 'email';
        inputEmail.value = email;

        form.appendChild(inputDomain);
        form.appendChild(inputEmail);
        document.body.appendChild(form);
        form.submit();
        document.body.removeChild(form);

        showToast('Đang tải backup...', 'info');

    } catch (err) {
        console.error('Error downloading backup:', err);
        showToast('Lỗi khi tải backup.', 'danger');
    } finally {
        if (btnElement) {
            btnElement.disabled = false;
            btnElement.classList.remove('disabled');
        }
    }
}

// ============================================================================
// 5. UTILITIES
// ============================================================================

/**
 * Escape HTML để chống XSS khi render dynamic content.
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}