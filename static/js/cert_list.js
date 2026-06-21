/**
 * cert_list.js
 * JS riêng cho trang Kho lưu trữ chứng chỉ SSL (templates/ssl/cert_list.html).
 * Phụ thuộc: common.js (phải load trước file này).
 */

document.addEventListener('DOMContentLoaded', () => {

    // --- KHỞI TẠO SỰ KIỆN GIAO DIỆN ---
    const btnOpenUpload = document.getElementById('btn-open-upload-modal');
    if (btnOpenUpload) {
        btnOpenUpload.addEventListener('click', () => {
            document.getElementById('ssl-form').reset();
            toggleModal('ssl-modal', true);
        });
    }

    // --- XỬ LÝ SUBMIT UPLOAD CHỨNG CHỈ TẬP TRUNG ---
    const sslForm = document.getElementById('ssl-form');
    if (sslForm) {
        sslForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData();
            formData.append('name', document.getElementById('ssl_name').value);
            formData.append('domain_id', document.getElementById('ssl_domain').value);
            formData.append('server_cert', document.getElementById('f_server').files[0]);
            formData.append('private_key', document.getElementById('f_key').files[0]);
            formData.append('root_cert', document.getElementById('f_root').files[0]);

            // Chỉ đính kèm file intermediate khi người dùng thực sự chọn để tối ưu payload
            const interFile = document.getElementById('f_inter').files[0];
            if (interFile) {
                formData.append('inter_cert', interFile);
            }

            // Gọi API thông qua postAndReload, truyền context 'event: e' để tự động khóa nút submit
            // tránh double submit tệp tin dung lượng lớn lên hệ thống.
            const result = await postAndReload(window.CERT_URLS.apiUploadCert, formData, {
                event: e,
                errorPrefix: 'Lỗi xác thực file' // Tiền tố thông báo tùy biến nếu backend báo lỗi khớp key
            });

            if (result && result.ok) {
                toggleModal('ssl-modal', false);
            }
        });
    }
});