/**
 * mailboxsoap_mailbox.js - UPDATED
 *
 * ⭐ Thêm:
 * - Modal tạo Email mới
 * - Hiển thị quota + used size trong search results
 * - Hiển thị quota bar trong edit modal
 */

document.addEventListener('DOMContentLoaded', () => {
    // ====================================================================
    // CONSTANTS
    // ====================================================================
    const API_SEARCH = '/soap/api/mailbox/search/';
    const API_DETAIL = '/soap/api/mailbox/detail/';
    const API_CREATE = '/soap/api/mailbox/create/';
    const API_UPDATE_PROFILE = '/soap/api/mailbox/update-profile/';
    const API_RESET_PASSWORD = '/soap/api/mailbox/reset-password/';
    const API_RENAME = '/soap/api/mailbox/rename/';
    const API_SET_STATUS = '/soap/api/mailbox/set-status/';
    const API_DELETE = '/soap/api/mailbox/delete/';
    const API_BACKUP = '/soap/api/mailbox/backup/';

    const searchForm = document.getElementById('mailboxSearchForm');
    const domainSelect = document.getElementById('domainSelect');
    const emailQueryInput = document.getElementById('emailQueryInput');
    const resultsTable = document.getElementById('mailboxResultsTable');
    const resultsBody = document.getElementById('mailboxResultsBody');
    const loadingDiv = document.getElementById('mailboxLoading');
    const emptyDiv = document.getElementById('mailboxEmptyState');

    let offset = 0;
    let hasMore = false;
    let currentDomainId = null;
    let currentQuery = '';

    // ====================================================================
    // 1. MODAL CREATE ACCOUNT
    // ====================================================================
    const createAccountModal = new bootstrap.Modal(document.getElementById('createAccountModal'));
    const btnOpenCreateAccount = document.getElementById('btnOpenCreateAccount');
    const createDomainSelect = document.getElementById('createDomain');
    const createEmailLocal = document.getElementById('createEmailLocal');
    const createDomainSuffix = document.getElementById('createDomainSuffix');
    const createGivenName = document.getElementById('createGivenName');
    const createSn = document.getElementById('createSn');
    const createDisplayName = document.getElementById('createDisplayName');
    const createPassword = document.getElementById('createPassword');
    const toggleCreatePassword = document.getElementById('toggleCreatePassword');
    const createQuota = document.getElementById('createQuota');
    const btnConfirmCreateAccount = document.getElementById('btnConfirmCreateAccount');

    if (btnOpenCreateAccount) {
        btnOpenCreateAccount.addEventListener('click', () => {
            document.getElementById('createAccountForm').reset();
            createDomainSelect.value = '';
            createDomainSuffix.textContent = '@domain.com';
            createAccountModal.show();
        });
    }

    // Update domain suffix when changed
    createDomainSelect.addEventListener('change', () => {
        const selected = createDomainSelect.options[createDomainSelect.selectedIndex];
        const domainName = selected.getAttribute('data-name') || 'domain.com';
        createDomainSuffix.textContent = '@' + domainName;
    });

    // Toggle password visibility
    toggleCreatePassword.addEventListener('click', () => {
        const type = createPassword.type === 'password' ? 'text' : 'password';
        createPassword.type = type;
        toggleCreatePassword.innerHTML = type === 'password'
            ? '<i class="bi bi-eye-slash"></i>'
            : '<i class="bi bi-eye"></i>';
    });

    // Create account submit
    btnConfirmCreateAccount.addEventListener('click', async () => {
        const domainId = createDomainSelect.value;
        if (!domainId) {
            showToast('Vui lòng chọn tên miền', 'warning');
            return;
        }

        const selected = createDomainSelect.options[createDomainSelect.selectedIndex];
        const domainName = selected.getAttribute('data-name');
        const emailLocal = createEmailLocal.value.trim();
        const email = emailLocal + '@' + domainName;
        const password = createPassword.value;
        const givenName = createGivenName.value.trim();
        const sn = createSn.value.trim();
        const displayName = createDisplayName.value.trim();
        const quota = createQuota.value;

        if (!emailLocal) {
            showToast('Vui lòng nhập phần local của email', 'warning');
            return;
        }

        if (!password || password.length < 8) {
            showToast('Mật khẩu phải có ít nhất 8 ký tự', 'warning');
            return;
        }

        btnConfirmCreateAccount.disabled = true;
        btnConfirmCreateAccount.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Đang tạo...';

        const formData = new FormData();
        formData.append('domain_id', domainId);
        formData.append('email_local', emailLocal);
        formData.append('domain_name', domainName);
        formData.append('password', password);
        formData.append('givenName', givenName);
        formData.append('sn', sn);
        formData.append('displayName', displayName);
        formData.append('quota_mb', quota);

        const result = await fetchJSON(API_CREATE, { method: 'POST', body: formData });

        btnConfirmCreateAccount.disabled = false;
        btnConfirmCreateAccount.innerHTML = '<i class="bi bi-check2 me-1"></i>Tạo Email';

        if (result.ok) {
            showToast(result.data.message || 'Đã tạo email mới thành công!', 'success');
            createAccountModal.hide();
            // Làm mới danh sách tìm kiếm
            offset = 0;
            if (currentDomainId) {
                performSearch();
            }
        } else {
            showToast(result.data.error || 'Lỗi tạo email', 'danger');
        }
    });

    // ====================================================================
    // 2. SEARCH & DISPLAY QUOTA
    // ====================================================================
    searchForm.addEventListener('submit', (e) => {
        e.preventDefault();
        currentDomainId = domainSelect.value;
        currentQuery = emailQueryInput.value;
        offset = 0;
        performSearch();
    });

    async function performSearch() {
        if (!currentDomainId) {
            showToast('Vui lòng chọn tên miền', 'warning');
            return;
        }

        loadingDiv.classList.remove('d-none');
        resultsTable.classList.add('d-none');
        emptyDiv.classList.add('d-none');

        const params = new URLSearchParams({
            domain_id: currentDomainId,
            q: currentQuery,
            offset: offset,
        });

        const result = await fetchJSON(`${API_SEARCH}?${params}`);

        loadingDiv.classList.add('d-none');

        if (result.ok) {
            const { results, has_more } = result.data;
            hasMore = has_more;

            if (offset === 0) {
                resultsBody.innerHTML = '';
            }

            if (results.length === 0 && offset === 0) {
                emptyDiv.classList.remove('d-none');
            } else {
                resultsTable.classList.remove('d-none');
                results.forEach(acc => {
                    resultsBody.innerHTML += buildRowHtml(acc);
                });
            }
        } else {
            showToast(result.data.error || 'Lỗi tìm kiếm', 'danger');
        }
    }

    function buildRowHtml(account) {
        const isUnlimited = !account.quota_mb || account.quota_mb === 0;
        const quotaPercent = (!isUnlimited && account.quota_mb > 0)
            ? Math.round((account.used_mb / account.quota_mb) * 100)
            : 0;

        const statusClass = {
            'active': 'badge bg-success',
            'locked': 'badge bg-warning',
            'closed': 'badge bg-secondary'
        }[account.status] || 'badge bg-secondary';

        return `
            <tr>
                <td class="font-monospace"><strong>${escapeHtml(account.email)}</strong>
                <br>${escapeHtml(account.displayName || '-')}
                </td>
                <td>${escapeHtml(account.sn || '-')}</td>
                <td>${escapeHtml(account.givenName || '-')}</td>
              
                <td>
                    <small class="text-muted">
                        ${account.used_mb.toFixed(1)}MB / ${isUnlimited ? 'Không giới hạn' : account.quota_mb.toFixed(1) + 'MB'}
                        ${!isUnlimited ? `<br><span class="badge bg-secondary">${quotaPercent}%</span>` : ''}
                    </small>
                </td>
                <td><span class="${statusClass}">${account.status}</span></td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-primary" onclick="openEditModal('${escapeAttr(account.email)}')" title="Sửa">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-info" onclick="openResetPassword('${escapeAttr(account.email)}')" title="Đặt lại mật khẩu">
                        <i class="bi bi-key"></i>
                    </button>
                    ${window.MAILBOX_CAN_MANAGE ? `
                    <button class="btn btn-sm btn-outline-secondary" onclick="downloadBackup('${escapeAttr(account.email)}')" title="Tải backup .tgz">
                        <i class="bi bi-download"></i>
                    </button>` : ''}
                </td>
            </tr>
        `;
    }

    // ====================================================================
    // 3. EDIT MODAL WITH QUOTA DISPLAY
    // ====================================================================
    const editAccountModal = new bootstrap.Modal(document.getElementById('editAccountModal'));
    const editDomainId = document.getElementById('editDomainId');
    const editOriginalEmail = document.getElementById('editOriginalEmail');
    const editEmailDisplay = document.getElementById('editEmailDisplay');
    const editUsedMb = document.getElementById('editUsedMb');
    const editQuotaMb = document.getElementById('editQuotaMb');
    const editQuotaBar = document.getElementById('editQuotaBar');
    const editQuotaPercent = document.getElementById('editQuotaPercent');
    const editQuotaInput = document.getElementById('editQuotaInput');
    const btnSaveAccountChanges = document.getElementById('btnSaveAccountChanges');
    const btnDeleteAccountInModal = document.getElementById('btnDeleteAccountInModal');

    window.openEditModal = async function(email) {
        const domainId = domainSelect.value;
        if (!domainId) {
            showToast('Vui lòng chọn tên miền trước', 'warning');
            return;
        }

        const result = await fetchJSON(`${API_DETAIL}?domain_id=${domainId}&email=${encodeURIComponent(email)}`);

        if (result.ok) {
            const { detail } = result.data;
            editDomainId.value = domainId;
            editOriginalEmail.value = email;
            editEmailDisplay.value = email;
            document.getElementById('editGivenName').value = detail.givenName || '';
            document.getElementById('editSn').value = detail.sn || '';
            document.getElementById('editDisplayName').value = detail.displayName || '';
            document.getElementById('editTitle').value = detail.title || '';
            document.getElementById('editMobile').value = detail.mobile || '';
            document.getElementById('editStatus').value = detail.status || 'active';
            document.getElementById('editNewEmail').value = '';

            // ⭐ Update quota display -- quota_mb === 0 nghĩa là không giới hạn
            const isUnlimited = !detail.quota_mb || detail.quota_mb === 0;
            const quotaPercent = (!isUnlimited && detail.quota_mb > 0)
                ? Math.round((detail.used_mb / detail.quota_mb) * 100)
                : 0;
            editUsedMb.textContent = detail.used_mb.toFixed(1);
            editQuotaMb.textContent = isUnlimited ? 'Không giới hạn' : detail.quota_mb.toFixed(1);
            editQuotaBar.style.width = quotaPercent + '%';
            editQuotaPercent.textContent = isUnlimited ? '—' : quotaPercent + '%';
            editQuotaInput.value = isUnlimited ? 0 : detail.quota_mb;

            // Color bar based on usage
            editQuotaBar.classList.remove('warning', 'danger');
            if (!isUnlimited && quotaPercent >= 90) {
                editQuotaBar.classList.add('danger');
            } else if (!isUnlimited && quotaPercent >= 70) {
                editQuotaBar.classList.add('warning');
            }

            editAccountModal.show();
        } else {
            showToast(result.data.error || 'Lỗi tải thông tin', 'danger');
        }
    };

    // Save changes
    btnSaveAccountChanges.addEventListener('click', async () => {
        const domainId = editDomainId.value;
        const email = editOriginalEmail.value;
        const newEmail = document.getElementById('editNewEmail').value.trim();
        const givenName = document.getElementById('editGivenName').value.trim();
        const sn = document.getElementById('editSn').value.trim();
        const displayName = document.getElementById('editDisplayName').value.trim();
        const title = document.getElementById('editTitle').value.trim();
        const mobile = document.getElementById('editMobile').value.trim();
        const status = document.getElementById('editStatus').value;
        const quotaRaw = editQuotaInput.value.trim();

        btnSaveAccountChanges.disabled = true;

        // Save profile
        let profileData = new FormData();
        profileData.append('domain_id', domainId);
        profileData.append('email', email);
        profileData.append('givenName', givenName);
        profileData.append('sn', sn);
        profileData.append('displayName', displayName);
        profileData.append('title', title);
        profileData.append('mobile', mobile);
        if (quotaRaw !== '') {
            profileData.append('quota_mb', quotaRaw);
        }

        const profileResult = await fetchJSON(API_UPDATE_PROFILE, { method: 'POST', body: profileData });

        // Rename if needed
        if (newEmail && newEmail !== email) {
            const renameData = new FormData();
            renameData.append('domain_id', domainId);
            renameData.append('email', email);
            renameData.append('new_email', newEmail);
            await fetchJSON(API_RENAME, { method: 'POST', body: renameData });
        }

        // Set status
        const statusData = new FormData();
        statusData.append('domain_id', domainId);
        statusData.append('email', email);
        statusData.append('status', status);
        await fetchJSON(API_SET_STATUS, { method: 'POST', body: statusData });

        btnSaveAccountChanges.disabled = false;

        if (profileResult.ok) {
            showToast('Đã lưu thay đổi thành công!', 'success');
            editAccountModal.hide();
            offset = 0;
            performSearch();
        } else {
            showToast(profileResult.data.error || 'Lỗi lưu thay đổi', 'danger');
        }
    });

    // Delete account
    btnDeleteAccountInModal.addEventListener('click', async () => {
        if (!confirm('Bạn chắc chắn muốn xóa vĩnh viễn tài khoản này? Không thể hoàn tác!')) {
            return;
        }

        const domainId = editDomainId.value;
        const email = editOriginalEmail.value;

        const formData = new FormData();
        formData.append('domain_id', domainId);
        formData.append('email', email);

        const result = await fetchJSON(API_DELETE, { method: 'POST', body: formData });

        if (result.ok) {
            showToast('Đã xóa tài khoản email!', 'success');
            editAccountModal.hide();
            offset = 0;
            performSearch();
        } else {
            showToast(result.data.error || 'Lỗi xóa tài khoản', 'danger');
        }
    });

    // ====================================================================
    // 4. RESET PASSWORD
    // ====================================================================
    const resetPasswordModal = new bootstrap.Modal(document.getElementById('resetPasswordModal'));
    const resetDomainId = document.getElementById('resetDomainId');
    const resetEmail = document.getElementById('resetEmail');
    const resetEmailDisplay = document.getElementById('resetEmailDisplay');
    const resetNewPassword = document.getElementById('resetNewPassword');
    const togglePassword = document.getElementById('togglePassword');
    const btnConfirmResetPassword = document.getElementById('btnConfirmResetPassword');

    window.openResetPassword = function(email) {
        const domainId = domainSelect.value;
        if (!domainId) {
            showToast('Vui lòng chọn tên miền trước', 'warning');
            return;
        }

        resetDomainId.value = domainId;
        resetEmail.value = email;
        resetEmailDisplay.textContent = email;
        resetNewPassword.value = '';
        resetPasswordModal.show();
    };

    togglePassword.addEventListener('click', () => {
        const type = resetNewPassword.type === 'password' ? 'text' : 'password';
        resetNewPassword.type = type;
        document.getElementById('toggleIcon').className = type === 'password'
            ? 'bi bi-eye-slash'
            : 'bi bi-eye';
    });

    btnConfirmResetPassword.addEventListener('click', async () => {
        const password = resetNewPassword.value;

        if (!password || password.length < 8) {
            showToast('Mật khẩu phải có ít nhất 8 ký tự', 'warning');
            return;
        }

        btnConfirmResetPassword.disabled = true;
        btnConfirmResetPassword.textContent = 'Đang xử lý...';

        const formData = new FormData();
        formData.append('domain_id', resetDomainId.value);
        formData.append('email', resetEmail.value);
        formData.append('new_password', password);

        const result = await fetchJSON(API_RESET_PASSWORD, { method: 'POST', body: formData });

        btnConfirmResetPassword.disabled = false;
        btnConfirmResetPassword.textContent = 'Xác nhận';

        if (result.ok) {
            showToast(result.data.message || 'Đã đặt lại mật khẩu!', 'success');
            resetPasswordModal.hide();
        } else {
            showToast(result.data.error || 'Lỗi đặt lại mật khẩu', 'danger');
        }
    });

    // ====================================================================
    // 5. BACKUP MAILBOX (.tgz)
    // ====================================================================
    window.downloadBackup = function(email) {
        const domainId = domainSelect.value;
        if (!domainId) {
            showToast('Vui lòng chọn tên miền trước', 'warning');
            return;
        }
        if (!confirm(`Tải file backup (.tgz) cho hộp thư ${email}?\nFile có thể khá lớn tùy dung lượng đã dùng.`)) {
            return;
        }

        const params = new URLSearchParams({
            domain_id: domainId,
            email: email,
        });
        // Điều hướng trực tiếp tới endpoint stream file -- để browser tự xử lý
        // download (Content-Disposition: attachment), không qua fetchJSON vì
        // response là binary stream, không phải JSON.
        window.location.href = `${API_BACKUP}?${params}`;
    };

    // ====================================================================
    // UTILITIES
    // ====================================================================
    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function escapeAttr(str) {
        if (!str) return '';
        return str.replace(/'/g, "\\'");
    }
});