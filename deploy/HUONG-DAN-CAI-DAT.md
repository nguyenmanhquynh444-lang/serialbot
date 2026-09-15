# Hướng dẫn cài Serial Paste Bot trên máy mới

Dành cho máy **chưa từng cài** bot. Máy đã có bot rồi thì chỉ cần bấm `Cap-nhat.bat`, bỏ
qua toàn bộ phần cài đặt bên dưới.

---

## 0. Kiểm tra trước khi bắt đầu

Thiếu một trong bốn thứ này thì cài xong bot cũng không chạy được việc gì:

| Cần có | Kiểm tra thế nào |
|---|---|
| **Windows 10 trở lên, bản 64-bit** | Chuột phải *This PC* → *Properties* → xem *System type* |
| **LDPlayer đã cài** | Mở thử LDPlayer, phải lên được màn hình Android |
| **App kho đã đăng nhập sẵn** trong LDPlayer | Mở app kho trong máy ảo, phải vào thẳng màn hình chính, không hỏi đăng nhập |
| **File Excel đơn hàng** | Chép sẵn vào máy, ví dụ để ở Desktop |

Bot **không tự cài LDPlayer** và **không tự đăng nhập** app kho. Hai việc đó làm trước.

> **Không cần cài Python.** Nếu ai đó bảo bạn chạy `python main.py` thì họ đưa nhầm mã
> nguồn — bản cài đã có sẵn Python bên trong. Gặp lỗi `Python was not found` là dấu hiệu
> của việc chép nhầm thư mục.

---

## 1. Cài đặt

Chọn **một** trong ba cách. Cách A tiện nhất vì về sau cập nhật cũng dùng lại đúng file đó.

### Cách A — dùng `Cap-nhat.bat` (khuyên dùng)

1. Xin file `Cap-nhat.bat` từ người phát hành, để ngoài **Desktop**.
2. Double-click vào nó.
3. Cửa sổ đen hiện ra, chờ khoảng một phút. Nó tự tải bộ cài rồi tự cài, không hỏi gì.
4. Cài xong app tự mở.

File này dùng được cho cả **cài mới lẫn cập nhật** — sau này ra bản mới, bấm lại đúng file
đó là xong, không phải xin file mới.

### Cách B — tải tay từ GitHub

Dùng khi `Cap-nhat.bat` báo lỗi tải (mạng công ty chặn, antivirus chặn…).

1. Mở link: https://github.com/nguyenmanhquynh444-lang/serialbot/releases/latest
2. Ở mục **Assets**, tải file **`SerialPasteBot-Setup.exe`** (~40 MB).
3. Chạy file vừa tải → **Tiếp tục** → **Cài đặt** → **Hoàn tất**.

Mặc định app cài cho **riêng tài khoản Windows đang dùng**, vào
`%LOCALAPPDATA%\Programs\Serial Paste Bot`, **không cần quyền admin, không hiện cửa sổ UAC**.
Muốn cài cho mọi tài khoản trên máy thì đổi ở trang đầu của trình cài (lúc đó mới cần admin).

### Cách C — bản portable, không cài

Dùng khi chỉ chạy tạm một buổi, hoặc máy không cho cài phần mềm.

1. Cũng ở link Releases trên, tải **`SerialPasteBot-Portable.exe`** (~57 MB).
2. Double-click là chạy, không cài gì lên máy.

Đổi lại: **mỗi lần mở chậm vài giây** (phải tự giải nén ra thư mục tạm), không có lối tắt
ngoài Desktop, và **không cập nhật được bằng `Cap-nhat.bat`** — ra bản mới phải tải tay lại.

---

## 2. Nếu Windows chặn khi mở lần đầu

Hiện bảng xanh **"Windows protected your PC"** là chuyện bình thường: file chưa mua chứng
thư ký số nên Windows chưa nhận ra người phát hành.

Bấm **More info** → **Run anyway**.

Nếu phần mềm diệt virus xoá mất file, báo người phát hành để họ gửi qua đường khác — đừng
tự tắt phần mềm diệt virus.

---

## 3. Mở app lần đầu

Mở **Serial Paste Bot** từ lối tắt ngoài Desktop hoặc trong Start Menu.

### 3.1. Kiểm tra bot có thấy máy ảo không

1. **Bật LDPlayer trước**, để máy ảo chạy hẳn lên màn hình Android.
2. Trong bot, bấm nút **Refresh**.
3. Danh sách instance phải hiện tên máy ảo của bạn. **Tick chọn** đúng một cái.

Bấm Refresh mà danh sách trống thì xem mục [Máy ảo không hiện ra](#máy-ảo-không-hiện-ra) ở
cuối trang.

### 3.2. Chọn file Excel và kiểm cột

1. Bấm chọn file Excel đơn hàng.
2. App tự đoán sheet và các cột theo dòng tiêu đề — **vẫn phải nhìn lại một lượt**, nhất là
   cột serial.
3. Chỉnh **hàng bắt đầu / hàng kết thúc** nếu chỉ chạy một phần danh sách.

> **Đóng file Excel đó trong Excel trước khi bấm Start.** Bot ghi kết quả thẳng vào file
> nguồn; đang mở thì bot vẫn chạy nhưng không ghi được kết quả.

### 3.3. Kiểm lại cấu hình kho

Đây là chỗ dễ sai nhất trên máy mới. Các ô cấu hình nhớ theo **từng tài khoản Windows**,
nên máy mới lần đầu chạy sẽ về giá trị mặc định:

| Ô | Mặc định | Phải làm gì |
|---|---|---|
| **Mã tote** | `T001` | Sửa cho đúng kho đang chạy |
| **Mã bin** | `PYTES` | Sửa cho đúng kho. Để trống nếu đơn trải nhiều vị trí, bot sẽ đi theo vị trí app chỉ |
| **Đối chiếu số lượng** | bật | **Cứ để bật.** Nó so số sản phẩm app báo với số serial trong Excel và dừng *trước khi mở phiên*, tức là lúc chưa động gì tới kho |

Hai mã mặc định trên là của kho hiện tại — **kho khác mà không sửa là lấy nhầm hàng**.

---

## 4. Chạy thử trước khi chạy thật

Đừng chạy cả danh sách ngay trong lần đầu trên máy mới.

1. Bấm **Start**.
2. Hộp **xem trước** hiện ra, cho tick từng mã. **Bỏ tick hết, chỉ chừa đúng một mã.**
3. Xác nhận và xem bot chạy trọn mã đó.
4. Đúng như mong đợi thì mới quay lại chạy cả danh sách.

Một mã chạy đúng là đủ để biết ADB thông, app kho phản hồi đúng, và cấu hình kho không sai.

---

## 5. Cập nhật về sau

Bấm lại `Cap-nhat.bat`. Nó tự tải bản mới nhất, tự đóng app nếu đang mở, cài đè rồi mở lại.

Không phải gỡ bản cũ trước. Kịch bản đã lưu, log và phiên chạy dở **không bị mất** — chúng
nằm trong `%LOCALAPPDATA%\SerialBot`, ngoài thư mục cài.

---

## 6. Gỡ cài đặt

**Settings → Apps → Serial Paste Bot → Uninstall**.

Trình gỡ sẽ hỏi có xoá luôn dữ liệu cá nhân (log, ảnh chụp, kịch bản đã lưu, phiên dở)
không. Định cài lại thì chọn **Không** để giữ kịch bản.

---

## Sự cố thường gặp

### Máy ảo không hiện ra

Bấm **Refresh** mà danh sách trống, lần lượt kiểm:

1. LDPlayer đã bật chưa, và đã lên hẳn màn hình Android chưa (đang khởi động thì chưa thấy).
2. Mở PowerShell gõ `adb devices` — phải thấy một dòng có chữ `device`.
3. LDPlayer cài ở chỗ lạ (không phải `C:\LDPlayer\...`) thì mở PowerShell chạy lệnh dưới
   rồi **mở lại bot**:

```
setx LDPLAYER_DIR "D:\Duong\Dan\Toi\LDPlayer9"
```

Chế độ **xuất kho theo mã OR chỉ chạy qua ADB**, không có đường lui gõ bàn phím, nên không
tìm thấy `adb.exe` là không chạy được. Bot sẽ báo thẳng có phải do thiếu `adb.exe` hay không.

### `Cap-nhat.bat` báo không tải được

Theo đúng thứ tự trong bảng thông báo của nó:

1. Kiểm tra máy có vào mạng được không.
2. Mở link Releases bằng trình duyệt xem tải tay có được không → được thì dùng **Cách B**.
3. Trình duyệt tải được mà file `.bat` thì không → nhiều khả năng antivirus hoặc proxy công
   ty chặn. Báo người phát hành.

### Bộ cài báo lỗi, không cài xong

Hay gặp nhất là **app vẫn đang chạy**. Đóng Serial Paste Bot, nhớ xem cả biểu tượng dưới
khay hệ thống (góc phải thanh taskbar), rồi chạy lại. Vẫn lỗi thì gửi mã lỗi hiện trên màn
hình cho người phát hành.

### Chạy xong không thấy kết quả trong Excel

Kiểm tra lúc bấm Start file có đang mở trong Excel không. Bot ghi thẳng vào file nguồn nên
file đang mở thì không ghi được. Đóng file rồi chạy lại.

### Cần gửi thông tin để người phát hành xem lỗi

Trong app: **Công cụ → Mở thư mục log**, gửi file log của phiên vừa chạy. Ảnh chụp lúc lỗi
nằm cùng chỗ, trong `%LOCALAPPDATA%\SerialBot\screenshots`.
