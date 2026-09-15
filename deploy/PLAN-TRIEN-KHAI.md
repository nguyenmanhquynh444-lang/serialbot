# Kế hoạch triển khai bản mới cho client

Trạng thái tính tới **18/08/2026**. File này ghi *đang làm tới đâu*; còn quy trình lặp lại
mỗi lần phát hành nằm ở [`README.md`](README.md) cùng thư mục.

## Vì sao có việc này

Máy client báo `Python was not found` khi chạy `python main.py` trong
`C:\Program Files\bot auto`. Nguyên nhân: ai đó chép **mã nguồn** sang máy client thay vì
cài bằng bộ cài. Client không cần Python — bản đóng gói đã nhúng sẵn Python và PyQt.

Đào thêm thì lòi ra vấn đề thật, nặng hơn: bộ cài đang phát hành là bản build **03/08**,
trong khi code mới nhất là **12/08**. Có 11 file `.py` sửa sau ngày build đó, gồm cả
`bot_worker.py`, `bot_gui.py`, `automation_backend.py`, `pick_runner.py`. Nghĩa là máy
client đang chạy code cũ hơn máy dev gần hai tuần.

## Phương án đã chọn

Host bộ cài trên **GitHub Releases** ở một link cố định. Client giữ sẵn một file
`Cap-nhat.bat` trên Desktop, ra bản mới thì bấm lại đúng file đó.

Đã cân nhắc và loại: viết cơ chế tự kiểm tra bản mới trong app (tốn ~nửa ngày code, để
dành khi nào số máy client nhiều lên), winget/MSIX (thừa cho vài máy nội bộ).

## Đã xong

- [x] **Tăng phiên bản 2.0.0 → 2.1.0** — [`version.py`](../version.py) và
      [`version_info.txt`](../version_info.txt) (cả tuple số lẫn hai chuỗi
      `FileVersion`/`ProductVersion`)
- [x] **Build bộ cài 2.1.0** — `dist\installer\SerialPasteBot-Setup.exe`, 39.9 MB.
      Đã đặt tên không kèm số phiên bản để khớp link cố định; bản gốc
      `SerialPasteBot-Setup-2.1.0.exe` giữ lại làm lưu trữ
- [x] **Build portable 2.1.0** — `dist\portable\SerialPasteBot.exe`, 57 MB
- [x] **[`Cap-nhat.bat`](Cap-nhat.bat)** — script client double-click: tải bộ cài mới nhất,
      tự đóng app nếu đang mở, cài đè im lặng, đọc registry tìm nơi đã cài rồi mở lại app.
      Không cần quyền admin, không hiện UAC
- [x] **[`README.md`](README.md)** — quy trình phát hành 4 bước
- [x] **[README chính](../README.md)** — thêm mục *Đẩy bản mới xuống máy client*, và một
      callout giải thích lỗi `Python was not found`
- [x] **[`.gitignore`](../.gitignore)** — viết lại, chặn dữ liệu kho thật khỏi repo public
- [x] **Repo GitHub** — `nguyenmanhquynh444-lang/serialbot`, public, đã có commit đầu tiên
      (`86e2a05 Create Readme`) nên mục Releases đã mở khoá
- [x] **Publish release `v2.1.0`** — https://github.com/nguyenmanhquynh444-lang/serialbot/releases/tag/v2.1.0
      với hai asset: `SerialPasteBot-Setup.exe` (39.8 MB) và `SerialPasteBot-Portable.exe`
      (56.9 MB). Link cố định của `Cap-nhat.bat` đã sống

## Đã kiểm chứng tới đâu

Phân biệt rõ để sau này không tưởng nhầm là đã test hết:

| Hạng mục | Kết quả |
|---|---|
| Version resource của `.exe` sau build | Đọc ra đúng `2.1.0` (cả bộ cài lẫn portable) |
| `Cap-nhat.bat` tải file 40 MB | Chạy thật qua HTTP, tải xong bình thường |
| `Cap-nhat.bat` gặp link hỏng (404) | Vào đúng nhánh báo lỗi, thoát mã 1, hướng dẫn hiện đủ |
| Tiếng Việt có dấu trong cửa sổ cmd | Hiện đúng nhờ `chcp 65001` |
| Đoạn đọc registry `InstallLocation`/`DisplayVersion` | Ghép đường dẫn `.exe` đúng |
| Các luật `.gitignore` | Test bằng repo git tạm, `data chạy/` khớp dù tên có dấu |
| Link cố định `/releases/latest/download/` sau khi publish | HTTP 200, tải về 39.9 MB trong 5.3 giây |
| File tải từ link đó | Header `MZ`, FileVersion `2.1.0`, SHA256 khớp đúng bản build trên máy dev |
| **Bước cài `/VERYSILENT` thật + mở lại app** | **CHƯA test** — máy dev chưa cài app nên không có gì để cài đè |
| **Toàn bộ luồng end-to-end trên máy client** | **CHƯA test** |

## Còn phải làm

- [ ] **Gửi `Cap-nhat.bat` cho client và chạy thử trên một máy thật** — bước duy nhất còn
      lại chứng minh cả chuỗi chạy được đầu-cuối. Đặt file ngoài Desktop máy client
- [ ] Xoá `dist\installer\SerialPasteBot-Setup-2.0.0.exe` và file `.zip` cũ cho khỏi lỡ tay
      upload nhầm bản cũ

## Những chỗ dễ hỏng

**Tên asset không được kèm số phiên bản.** Link cố định là:

```
https://github.com/nguyenmanhquynh444-lang/serialbot/releases/latest/download/SerialPasteBot-Setup.exe
```

Upload file tên `SerialPasteBot-Setup-2.1.0.exe` là link trên gãy và **mọi máy client mất
đường cập nhật cùng lúc**. Phải đổi tên file trên máy trước khi kéo vào release — web
GitHub không cho sửa tên asset sau khi đã upload.

**Repo phải để public.** Link `/releases/latest/download/` của repo private đòi token,
`Cap-nhat.bat` sẽ nhận 404 và client không hiểu vì sao.

**Đừng đổi `AppId`** trong [`installer/SerialPasteBot.iss`](../installer/SerialPasteBot.iss).
Inno Setup dựa vào nó để nhận ra bản đã cài mà cài đè; đổi là máy client mọc hai mục
Serial Paste Bot trong Apps & features.

**Nếu đẩy mã nguồn lên repo public**: `.gitignore` đã chặn `data chạy/` (chứa `data.xlsx`
và các file `data_ket_qua_*.xlsx` là đơn thật của kho), `logs/`, `screenshots/` và
`.claude/settings.local.json`. Đừng xoá mấy dòng đó. `recipes/classic.json` thì **phải
giữ tracked** — `SerialPasteBot.spec` nhúng nó vào app lúc build.

**"Không cần cài gì thêm" chỉ đúng với Python và thư viện.** Máy client vẫn phải có
**LDPlayer** và **app kho đã đăng nhập sẵn** trong máy ảo; bot không tự cài LDPlayer, cũng
không tự đăng nhập. Xem mục *Chuyển bot sang máy khác* trong README chính.

**Antivirus / SmartScreen.** File `.exe` do PyInstaller sinh ra và chưa ký số nên thỉnh
thoảng bị chặn. Nếu gặp nhiều, cách xử lý gốc là mua chứng thư ký code rồi ký `.exe`
trước khi upload.
