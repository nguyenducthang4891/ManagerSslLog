2. Hướng dẫn sử dụng trong các trang kế thừa
Dưới đây là 2 kịch bản thực tế nhất khi bạn viết code ở các file như domain_list.js, server_list.js:

Trường hợp 1: Hành động trực tiếp trên danh sách (Ví dụ: Nút "Xóa" nhanh)
Nút bấm nằm ngay trên hàng của bảng (table), bấm vào hiện confirm() và thực hiện xóa.

HTML trong trang danh sách:

HTML
<button class="btn btn-sm btn-danger btn-delete-domain" data-id="12">Xóa</button>
JS trong file domain_list.js:

JavaScript
document.querySelectorAll('.btn-delete-domain').forEach(button => {
    button.addEventListener('click', async (e) => {
        const domainId = e.target.dataset.id; // Lấy ID từ data attribute

        // Gọi hàm và chỉ cần truyền thêm `event: e`
        await postAndReload(`/api/domain/delete/${domainId}/`, null, {
            confirmMessage: 'Bạn có chắc chắn muốn xóa domain này không?',
            event: e // Tự động khóa nút bấm này lại, thành công sẽ tự reload trang
        });
    });
});
Trường hợp 2: Hành động nằm trong Modal (Ví dụ: Form "Thêm mới" hoặc "Cập nhật")
Người dùng điền thông tin vào Form trong Modal, sau đó bấm nút "Lưu thay đổi" nằm ở góc dưới Modal.

HTML cấu trúc Modal (Bootstrap 5):

HTML
<div class="modal fade" id="addDomainModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <form id="addDomainForm">
        <div class="modal-body">
          <input type="text" name="domain_name" class="form-control" placeholder="Nhập tên domain">
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Đóng</button>
          <button type="submit" class="btn btn-primary" id="btnSubmitForm">Lưu thay đổi</button>
        </div>
      </form>
    </div>
  </div>
</div>
JS xử lý sự kiện submit Form trong domain_list.js:

JavaScript
const form = document.getElementById('addDomainForm');

form.addEventListener('submit', async (e) => {
    e.preventDefault(); // Ngăn form load lại trang theo cách truyền thống

    // Thu thập toàn bộ dữ liệu trong các input của Form
    const formData = new FormData(form); 

    // Thực hiện gọi API qua postAndReload
    const result = await postAndReload('/api/domain/add/', formData, {
        event: e // Khóa luôn nút submit "Lưu thay đổi" lại để tránh double-submit dữ liệu
    });

    if (result && result.ok) {
        // Nếu xử lý thành công, ẩn modal đi trước khi trang bị reload (tăng trải nghiệm mượt mà)
        toggleModal('addDomainModal', false);
    }
});