# Phát hành bản mới cho client

Quy trình cố định, 4 bước. Làm đúng thứ tự thì client không phải nhận file mới bao giờ
nữa — họ giữ nguyên `Cap-nhat.bat` đã có và bấm lại mỗi khi cần lên bản mới.

## 1. Tăng số phiên bản

Sửa `APP_VERSION` trong [`version.py`](../version.py), và sửa cho khớp trong
[`version_info.txt`](../version_info.txt) (cả `filevers`/`prodvers` dạng tuple lẫn hai
chuỗi `FileVersion`/`ProductVersion`).

Bỏ qua bước này thì bộ cài vẫn chạy được, nhưng hộp About và tab Details của file .exe
sẽ báo sai bản — về sau không ai truy được máy client đang chạy code ngày nào.

## 2. Build

```
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

Ra `dist/installer/SerialPasteBot-Setup-<ver>.exe`.

## 3. Upload — đổi tên bỏ số phiên bản

Đây là bước quan trọng nhất và cũng dễ quên nhất.

**Đổi tên file trên máy TRƯỚC khi upload**, bỏ hẳn số phiên bản:

```
dist\installer\SerialPasteBot-Setup-2.1.0.exe  ->  SerialPasteBot-Setup.exe
```

Phải làm ở bước này vì giao diện web của GitHub không cho sửa tên asset sau khi đã
upload — kéo nhầm file có số vào rồi thì phải xoá asset đi và upload lại.

Rồi tạo release ở https://github.com/nguyenmanhquynh444-lang/serialbot/releases/new
(tag đặt theo phiên bản, ví dụ `v2.1.0`) và kéo file vừa đổi tên vào. Link tải luôn là:

```
https://github.com/nguyenmanhquynh444-lang/serialbot/releases/latest/download/SerialPasteBot-Setup.exe
```

GitHub tự trỏ `latest` sang release mới nhất, nên link này không đổi qua các phiên bản —
đó là lý do `Cap-nhat.bat` chỉ cần phát cho client đúng một lần. Để nguyên tên có số
phiên bản là link trên gãy ngay và mọi máy client mất đường cập nhật.

Repo phải **để public**. Link `/releases/latest/download/` của repo private đòi token,
`Cap-nhat.bat` sẽ nhận về lỗi 404 và client không hiểu vì sao.

## 4. Gửi Cap-nhat.bat cho client (chỉ lần đầu)

[`Cap-nhat.bat`](Cap-nhat.bat) đã trỏ sẵn vào repo trên, không phải sửa gì. Gửi client
đúng một file này, đặt đâu cũng được (Desktop là tiện nhất). Về sau ra bản mới chỉ cần
báo họ bấm lại đúng file đó — không gửi lại file mới bao giờ nữa.

---

## Client cần biết gì

Máy **đã có bot** rồi thì đúng một câu: **double-click `Cap-nhat.bat`, đợi khoảng một phút.**

Script tự tải bộ cài, tự đóng app nếu đang mở, cài đè, rồi mở lại app. Không cần cài
Python, không cần quyền admin, không hiện UAC (bộ cài đặt `PrivilegesRequired=lowest`,
cài vào `%LOCALAPPDATA%\Programs\Serial Paste Bot`).

Máy **mới tinh** thì gửi kèm hướng dẫn cài — đầy đủ từ khâu chuẩn bị LDPlayer, ba cách
cài, kiểm cấu hình kho, chạy thử một mã, tới xử lý các sự cố hay gặp. Có hai bản, cùng
một nội dung:

- **Trang web** (dễ đọc trên điện thoại, gửi bằng link):
  https://claude.ai/artifact/DpEZWGygmtP8BgYa8UNHoY
  Nguồn là [`huong-dan-cai-dat.html`](huong-dan-cai-dat.html) — sửa file đó rồi publish
  lại là trang tự cập nhật, link giữ nguyên. Link này ở chế độ riêng tư mặc định —
  vào trang, bấm nút Share, chọn "Anyone with the link" thì client mới xem được.
- **File markdown**: [`HUONG-DAN-CAI-DAT.md`](HUONG-DAN-CAI-DAT.md)

Sửa nội dung thì nhớ sửa **cả hai** cho khỏi lệch.

Người vận hành kho (chạy nhập hàng theo mã check-in, xuất kho theo mã OR) thì gửi thêm
[`HUONG-DAN-NHAP-XUAT-SERIAL.md`](HUONG-DAN-NHAP-XUAT-SERIAL.md). Tài liệu này chỉ có bản
markdown, chưa có bản trang web.

Dữ liệu cá nhân — log, ảnh chụp, kịch bản đã lưu, phiên chạy dở trong
`%LOCALAPPDATA%\SerialBot` — nằm ngoài thư mục cài nên cập nhật không đụng tới.

**Client không bao giờ cần chép source code hay chạy `python main.py`.** Bản đóng gói đã
nhúng sẵn Python và PyQt trong file .exe.

## Vài chỗ dễ vấp

**Đừng đổi `AppId`** trong [`installer/SerialPasteBot.iss`](../installer/SerialPasteBot.iss).
Inno Setup dựa vào nó để nhận ra bản đã cài mà cài đè; đổi là máy client mọc hai mục
Serial Paste Bot trong Apps & features và hai lối tắt trỏ vào hai thư mục khác nhau.

**Cài đè không cần gỡ bản cũ trước.** Cứ chạy thẳng bộ cài mới.

**Antivirus.** File .exe do PyInstaller sinh ra và chưa ký số nên thỉnh thoảng bị
SmartScreen hoặc antivirus doanh nghiệp chặn. Nếu gặp nhiều, cách xử lý gốc là mua chứng
thư ký code (code signing certificate) rồi ký file .exe trước khi upload.
