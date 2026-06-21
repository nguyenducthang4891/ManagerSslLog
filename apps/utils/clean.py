def clean_certificate_content(raw_content) -> bytes:
    """
    Hàm chuẩn hóa dữ liệu chứng chỉ:
    Xử lý triệt để lỗi bị bọc b'...' và lỗi ký tự xuống dòng literal '\\r\\n'
    """
    if isinstance(raw_content, bytes):
        content = raw_content.decode('utf-8', errors='replace')
    else:
        content = str(raw_content)

    content = content.strip()

    # 1. Bóc vỏ b'...' hoặc b"..." nếu bị lỗi ép kiểu str(bytes) ngoài ý muốn
    if content.startswith("b'") and content.endswith("'"):
        content = content[2:-1]
    elif content.startswith('b"') and content.endswith('"'):
        content = content[2:-1]

    # 2. Biến đổi các ký tự xuống dòng dạng chữ '\\r\\n' thành thực thể xuống dòng thật
    content = content.replace('\\r\\n', '\n').replace('\\n', '\n')
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    # 3. Làm sạch khoảng trống từng dòng và ghép lại chuẩn POSIX
    lines = [line.strip() for line in content.split('\n') if line.strip()]

    return '\n'.join(lines).encode('utf-8') + b'\n'