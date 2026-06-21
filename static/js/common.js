/**
 * common.js
 * Các helper dùng chung cho toàn bộ giao diện (Bootstrap 5).
 * Base.html phải load file này TRƯỚC khi load JS riêng của từng trang.
 */

/**
 * Lấy CSRF token từ thẻ <meta name="csrf-token"> trong base.html.
 */
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

/**
 * Mở/đóng Bootstrap Modal bằng id.
 * @param {string} id - id của phần tử .modal
 * @param {boolean} show - true để mở, false để đóng
 */
function toggleModal(id, show) {
    const el = document.getElementById(id);
    if (!el) return;
    const modal = bootstrap.Modal.getOrCreateInstance(el);
    if (show) {
        modal.show();
    } else {
        modal.hide();
    }
}

/**
 * Hiển thị thông báo dạng Bootstrap Toast (Đã vá lỗi bảo mật XSS).
 * @param {string} message - nội dung thông báo
 * @param {'success'|'danger'|'warning'|'info'} type - loại thông báo
 */
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) {
        alert(message); // Fallback nếu base.html thiếu container
        return;
    }

    const toastEl = document.createElement('div');
    toastEl.className = `toast align-items-center text-white bg-${type} border-0`;
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');

    // Khung giao diện Toast
    toastEl.innerHTML = `
        <div class="d-flex">
            <div class="toast-body"></div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    // BẢO MẬT: Dùng textContent thay vì innerHTML để chống tấn công Stored XSS
    toastEl.querySelector('.toast-body').textContent = message;

    container.appendChild(toastEl);

    const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
    toast.show();

    // HIỆU NĂNG: Xóa DOM node ngay khi ẩn để tránh rác bộ nhớ (DOM Leaking)
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

/**
 * Wrapper fetch() chuẩn hóa, tự đính kèm CSRF token.
 * @param {string} url
 * @param {object} options
 * @returns {Promise<{ok: boolean, status: number, data: object}>}
 */
async function fetchJSON(url, options = {}) {
    const headers = Object.assign({'X-CSRFToken': getCsrfToken()}, options.headers || {});

    try {
        const res = await fetch(url, Object.assign({}, options, {headers}));
        let data = {};
        try {
            data = await res.json();
        } catch (parseErr) {
            data = {error: 'Phản hồi từ server không đúng định dạng JSON.'};
        }
        return {ok: res.ok, status: res.status, data};
    } catch (networkErr) {
        return {ok: false, status: 0, data: {error: 'Lỗi kết nối mạng. Vui lòng kiểm tra đường truyền.'}};
    }
}

/**
 * Helper gọi API POST, hiện toast và tự động reload.
 * HIỆU NĂNG & UX: Tự động khóa (disable) nút bấm dựa vào `event` để chống Double Submit.
 * * @param {string} url
 * @param {FormData|null} formData
 * @param {object} opts - { confirmMessage, successReload, event }
 */
async function postAndReload(url, formData = null, opts = {}) {
    if (opts.confirmMessage && !confirm(opts.confirmMessage)) {
        return;
    }

    // HIỆU NĂNG: Khóa nút bấm ngay lập tức khi click để tránh người dùng bấm liên tiếp
    let triggerBtn = null;
    if (opts.event && opts.event.target) {
        triggerBtn = opts.event.target.closest('button, a');
        if (triggerBtn) {
            triggerBtn.classList.add('disabled', 'pe-none'); // Khóa bằng class Bootstrap 5
        }
    }

    const result = await fetchJSON(url, {method: 'POST', body: formData});

    if (result.ok) {
        showToast(result.data.message || 'Thao tác thành công!', 'success');
        if (opts.successReload !== false) {
            // Chờ toast hiển thị một chút rồi reload
            setTimeout(() => location.reload(), 700);
        } else if (triggerBtn) {
            // Nếu không reload, trả lại trạng thái hoạt động cho nút
            triggerBtn.classList.remove('disabled', 'pe-none');
        }
    } else {
        showToast(result.data.error || 'Đã xảy ra lỗi không xác định.', 'danger');
        // Thất bại thì phải mở khóa nút để người dùng bấm lại
        if (triggerBtn) {
            triggerBtn.classList.remove('disabled', 'pe-none');
        }
    }
    return result;
}