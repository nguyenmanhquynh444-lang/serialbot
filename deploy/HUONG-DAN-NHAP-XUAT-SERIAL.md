# Hướng dẫn cài đặt và sử dụng: nhập hàng và xuất kho theo serial

Áp dụng cho **Serial Paste Bot 2.2.0**. Tài liệu này đi một mạch từ máy trắng tới lúc có
kết quả trong Excel, cho hai việc:

| Việc | Chọn ở ô **Kiểu chạy** | Đơn vị công việc | File Excel cần có |
|---|---|---|---|
| **Xuất kho** | *Theo mã OR (xuất kho)* | Mỗi mã OR là một phiên lấy hàng | Cột **OR**, cột **MVĐ**, cột **Serial** |
| **Nhập hàng** | *Theo mã check-in (nhập hàng)* | Mỗi mã check-in là một phiếu nhập | Cột **Mã check-in**, cột **Serial** |

Hai chế độ này cùng một nguyên tắc: **gặp bất thường là dừng cả lượt**, không bỏ qua dòng
rồi chạy tiếp. Quét lẫn serial sang phiên khác là xuất/nhập nhầm đơn thật, nên bot thà
dừng còn hơn đoán.

> Bot thao tác trên **hệ thống kho thật** qua LDPlayer. Chưa quen thì làm đúng mục
> [4. Chạy thử một mã](#4-chạy-thử-một-mã-trước-khi-chạy-cả-danh-sách) trước, đừng chạy
> thẳng cả danh sách.

---

## 1. Chuẩn bị

Thiếu một trong các thứ dưới đây thì cài xong bot cũng chưa chạy được:

| Cần có | Kiểm tra |
|---|---|
| Windows 10 trở lên, 64-bit | *This PC* → *Properties* → *System type* |
| **LDPlayer** đã cài, mở lên được màn hình Android | Mở thử LDPlayer |
| **App kho đã đăng nhập sẵn** trong LDPlayer | Mở app, phải vào thẳng màn hình chính, không hỏi đăng nhập |
| **File Excel** đúng mẫu ở mục 3 | Chép sẵn ra Desktop |

Bot **không tự cài LDPlayer** và **không tự đăng nhập** app kho. Không cần cài Python.

## 2. Cài đặt

**Cách nhanh nhất:** xin file `Cap-nhat.bat` từ người phát hành, để ngoài Desktop, double-click
và chờ khoảng một phút. File này tự tải bộ cài, tự cài rồi mở app. Về sau ra bản mới, bấm
lại đúng file đó là cập nhật.

Hai cách khác (tải tay `SerialPasteBot-Setup.exe` từ trang Releases, hoặc bản portable
không cài) và cách xử lý khi Windows hiện bảng *"Windows protected your PC"* nằm trong
[`HUONG-DAN-CAI-DAT.md`](HUONG-DAN-CAI-DAT.md).

Cài xong, mở **Serial Paste Bot** từ Desktop hoặc Start Menu.

### Kiểm tra bot có thấy máy ảo

1. **Bật LDPlayer trước**, chờ lên hẳn màn hình Android.
2. Trong bot bấm **Refresh**. Danh sách instance phải hiện tên máy ảo.
3. Tick **đúng một** instance. Hai chế độ này chỉ chạy trên **một** máy ảo: một phiên là
   một tài khoản đang thao tác kho, chia ra nhiều máy là làm nhầm đơn.

Danh sách trống thì xem mục [Sự cố thường gặp](#8-sự-cố-thường-gặp).

Muốn thử riêng kết nối: menu **Công cụ → Kiểm tra kết nối ADB**.

---

## 3. Chuẩn bị file Excel

Quy tắc chung cho cả hai chế độ:

- Có **dòng tiêu đề** ở trên cùng (không bắt buộc, nhưng nên có; không có thì phải đặt
  *Start row* = 1).
- **Đóng file trong Excel trước khi bấm Start.** Bot ghi kết quả thẳng vào file nguồn;
  đang mở thì không ghi được.
- Cột serial phải là **giá trị thật**, không phải công thức. Cột là công thức
  (VLOOKUP, ghép chuỗi…) thì bot đọc ra rỗng; bot sẽ hỏi trước khi chạy, lúc đó dán-đè
  cột thành giá trị (Paste Values).
- Một mã có nhiều serial thì **lặp mã ở từng dòng**, hoặc để **ô gộp** trải nhiều dòng.
  Bot đọc được cả hai.

### Xuất kho: ba cột OR / MVĐ / Serial

| | A — OR | B — MVĐ | C — Seri |
|---|---|---|---|
| 1 | *OR* | *MVĐ* | *Seri* |
| 2 | ORVINEKGK4T1560 | 581PIPTE03082026 | E52771260715N01954 |
| 3 | ORVINT8L5UY9235 | 580PIPTE03082026 | E52771260715N01854 |

Ví dụ trên là 2 phiên lấy hàng, mỗi phiên 1 serial.

- Ô tìm của màn hình *Lấy hàng* nhận **mã OR**, không phải mã vận đơn. Cột **MVĐ** chỉ để
  ghi vào kết quả và báo cáo cho dễ tra ngược, bot **không gõ** nó vào đâu.
- Mở file xong, bot **tự điền** các ô cột theo dòng tiêu đề (`OR`, `MVĐ`, `Serial`/`Seri`/`IMEI`).
  Vẫn nên nhìn lại một lượt.

### Nhập hàng: hai cột Mã check-in / Serial

| | A — Ma check-in | B — Serial |
|---|---|---|
| 1 | *Ma check-in* | *Serial* |
| 2 | CKSIRVIN89HN210210 | E52771260430D01999 |
| 3 | CKSIRVIN89HN210210 | E52771260509N00734 |
| 4 | CKSIRVIN9NWS373102 | E52771260412D01939 |

- Điền **mã check-in** (`CKSIRVIN89HN210210`), **mã nhập kho** (`IRVIN89HN210`) hoặc **mã yêu
  cầu** (`167PIVGR27072026`) đều được; ô tìm của app nhận cả ba.
- Với nhập hàng, bot **không tự đoán** ô *Cột mã check-in* theo tiêu đề. Mặc định ô này là
  `A`; file của bạn để mã ở cột khác thì **sửa tay**.

---

## 4. Chạy thử một mã trước khi chạy cả danh sách

Làm bước này ở **lần đầu trên mỗi máy**, và sau mỗi lần cập nhật bản mới:

1. Làm theo mục 5 (xuất kho) hoặc mục 6 (nhập hàng) tới bước bấm **Start**.
2. Hộp **Xem trước** hiện ra: **bỏ tick hết, chỉ chừa đúng một mã**, rồi xác nhận.
3. Xem bot chạy trọn mã đó, kiểm lại trên app kho.
4. Đúng như mong đợi thì mới quay lại chạy cả danh sách.

Một mã chạy đúng là đủ để biết ADB thông, app phản hồi đúng và cấu hình kho không sai.

---

## 5. Xuất kho (theo mã OR)

### 5.1. Các bước

1. Đổi **Kiểu chạy** sang *Theo mã OR (xuất kho)*. Khung *Xuất kho theo mã OR* hiện ra ở
   trang **Cấu hình**.
2. **Chọn file Excel** (nút **Browse**, `Ctrl+O`, hoặc kéo thả file `.xlsx` vào cửa sổ).
3. Kiểm tra các ô:

   | Ô | Mặc định | Ghi chú |
   |---|---|---|
   | **Cột mã OR** | `A` | Tự điền theo tiêu đề |
   | **Cột MVĐ** | `B` | Để trống nếu file không có cột này |
   | **Serial column** | `H` | Phải **khác** hai cột trên, trùng là báo lỗi ngay |
   | **Start row / End row** | `2` / `0` (không giới hạn) | Chỉnh nếu chỉ chạy một phần |
   | **Mã tote** | `T001` | **Sửa cho đúng kho đang chạy** |
   | **Mã bin** | `PYTES` | **Sửa cho đúng kho.** Để trống nếu đơn trải nhiều vị trí, bot đi theo vị trí app chỉ |
   | **Đối chiếu số lượng** | bật | **Cứ để bật.** Lệch số lượng thì bot dừng *trước khi mở phiên*, lúc chưa động gì tới kho |

   Mã tote và mã bin mặc định là của kho hiện tại. **Kho khác mà không sửa là lấy nhầm hàng.**
   Hai ô này giữ nguyên suốt lượt chạy; muốn đổi thì dừng rồi chạy lại.

4. Bấm **Refresh**, tick **đúng một** instance.
5. Mở sẵn màn hình **Lấy hàng** trên LDPlayer, hoặc để ở menu chính (bot tự bấm vào).
6. Bấm **Start**. Hộp **Xem trước - chạy theo mã OR** hiện ra: **đọc kỹ phần cảnh báo ở đầu
   hộp**, đây là chỗ duy nhất thấy dữ liệu bẩn trước khi bot động vào kho thật. Bỏ tick mã
   chưa muốn chạy, rồi xác nhận.
7. Theo dõi thanh tiến độ (ví dụ `3 / 12 mã OR`) và thanh trạng thái (bước hiện tại).
8. Xong thì làm theo [mục 7](#7-xem-kết-quả).

### 5.2. Trong mỗi mã OR, bot làm gì

Bot tìm mã OR → chỉ bấm khi lọc ra **đúng một** thẻ → đối chiếu số lượng → vào tote → vào
bin → quét từng serial (chờ bộ đếm `0/N` tăng đúng một rồi mới gõ serial tiếp) → đóng
phiên → sang mã sau. Serial cuối cùng thì app tự đóng phiên và hiện hộp thoại kết thúc; bot
xem hộp thoại đó là dấu hiệu xong.

### 5.3. Cảnh báo trong hộp Xem trước

| Cảnh báo | Nghĩa là gì / nên làm gì |
|---|---|
| Cột mã OR trỏ nhầm vào cột serial | Sửa lại ô *Cột mã OR* |
| Serial trùng nhau | Kiểm tra hai dòng được nêu |
| Một mã OR tách thành hai cụm rời | File có thể bị sắp lẫn; chạy tiếp sẽ thành hai phiên riêng |
| Một mã OR mang hai MVĐ khác nhau | Báo cáo chỉ giữ MVĐ đầu tiên |
| Serial nằm phía trên mã OR đầu tiên | Dòng đó bị bỏ qua |

---

## 6. Nhập hàng (theo mã check-in)

### 6.1. Các bước

1. Đổi **Kiểu chạy** sang *Theo mã check-in (nhập hàng)*. Khung đổi thành *Nhập hàng theo
   mã check-in*; các ô Cột MVĐ, Mã tote, Mã bin bị khóa vì không dùng ở chế độ này.
2. **Chọn file Excel**, kiểm tra **Cột mã check-in**, **Serial column**, **Start row / End row**.
3. Giữ bật **Đối chiếu số lượng**.
4. Bấm **Refresh**, tick **đúng một** instance, để app ở menu chính (bot tự bấm
   **Receive / Nhận hàng**).
5. Bấm **Start**, đọc cảnh báo trong hộp xem trước, rồi xác nhận.

### 6.2. Trong mỗi phiếu, bot làm gì

Bot bấm Receive → gõ mã + Enter vào ô tìm → lọc còn **đúng một** thẻ thì bấm *Nhận hàng*
→ đối chiếu tổng `0/N` với số serial trong Excel (lệch là dừng, chưa quét serial nào) →
quét từng serial → đóng phiếu → về danh sách rồi sang phiếu sau.

### 6.3. Khi mã chưa có phiên check-in

Gõ một mã nhập kho chưa từng check-in, app hiện hộp *"Yêu cầu nhập kho chưa có tạo phiên
check-in? Bạn có muốn tạo phiên và nhận hàng"*, với hai nút **Quay lại** / **Xác nhận**.

Bấm **Xác nhận** là **tạo một phiên check-in thật** trong hệ thống. Vì vậy:

- **Mặc định:** bot bấm *Quay lại* rồi **dừng**, báo mã nào chưa có phiên để bạn tự quyết.
- Ô **"Tự tạo phiên check-in nếu chưa có"**: chỉ tick khi biết chắc **mọi** mã trong file
  đều cần tạo phiên mới. Tick nhầm là sinh ra một loạt phiên rác phải đi dọn.

### 6.4. Lưu ý riêng cho nhập hàng

Các màn hình *sau* nút *Nhận hàng* chưa được dò hết trên máy thật. Nếu app chèn thêm bước
mà bot chưa biết (quét thùng, chọn sản phẩm…), bot **dừng và liệt kê những gì đang hiện
trên màn hình** thay vì gõ serial vào ô lạ. Gặp trường hợp đó, gửi nguyên thông báo cho
người phát hành để bổ sung bước còn thiếu. Vì thế mục 4 (chạy thử một mã) đặc biệt quan
trọng với nhập hàng.

---

## 7. Xem kết quả

### 7.1. Trong file Excel

Khi chạy xong, mở lại file Excel nguồn: bot thêm một sheet **`Ket qua <thời điểm>`**, mỗi
lượt chạy một sheet riêng. Sheet dữ liệu gốc không bị chạm ô nào. Sheet gồm Hàng Excel,
Serial, Trạng thái, Phản hồi app, Thời gian, Lý do, Ảnh chụp.

### 7.2. Xuất báo cáo

Bấm **Export Report** để ra một file Excel riêng (đây là lúc duy nhất bot tạo file mới, và
chỉ khi bạn bấm):

| Sheet | Nội dung |
|---|---|
| **Summary** | Tổng hợp lượt chạy |
| **Ma OR** (xuất kho) hoặc **Check-in** (nhập hàng) | Từng mã: cần xuất/nhận, đã xuất/nhận, trạng thái, thông báo |
| **Chi tiet** | Từng serial |
| **Loi** | Chỉ các dòng không OK |

File báo cáo phải **khác** file nguồn.

### 7.3. Hai mức "thành công"

Thanh thống kê tách hai con số, đừng cộng gộp trong đầu:

| Con số | Ý nghĩa |
|---|---|
| **Đã xác nhận** | Có bằng chứng từ app (bộ đếm tăng đúng một, hoặc hộp thoại hoàn tất ở đúng serial cuối) |
| **Không phát hiện lỗi** | Bot không thấy lỗi nhưng **chưa có bằng chứng chắc chắn** là app đã nhận hàng |

Trạng thái `UNKNOWN` nghĩa là bot không xác nhận được (mất phản hồi, mất kết nối…), tuyệt
đối không đoán là `OK`. Cần thì đối chiếu thẳng trên app.

---

## 8. Sự cố thường gặp

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Bấm **Refresh** mà danh sách trống | LDPlayer chưa bật hẳn, hoặc ADB chưa thấy máy | Bật LDPlayer tới màn hình Android; PowerShell gõ `adb devices` phải thấy một dòng `device` |
| Bot báo thiếu `adb.exe` | LDPlayer cài ở chỗ lạ | `setx LDPLAYER_DIR "D:\Duong\Dan\LDPlayer9"` rồi **mở lại bot**. Hai chế độ này chỉ chạy qua ADB, không có đường lui gõ bàn phím |
| Dừng với lý do lọc ra 0 hoặc nhiều hơn 1 thẻ | Mã sai, mã mơ hồ khớp nhiều phiên, hoặc phiên đã xong từ trước | Kiểm tra mã trên app. Bot không bấm thẻ nào khi chưa chắc |
| Dừng vì lệch số lượng | Số sản phẩm app báo khác số serial trong Excel | Kiểm tra file; lúc này chưa quét serial nào nên chưa mất gì |
| Dừng vì app chỉ sang bin khác với ô **Mã bin** | Đơn trải nhiều vị trí | Để trống **Mã bin** nếu muốn đi theo app, hoặc kiểm tra lại đơn |
| Dừng vì hộp thoại lạ | App hiện hộp thoại bot chưa biết | Xem ảnh chụp và thông báo; **không bấm bừa**. Gửi cho người phát hành |
| Không thấy kết quả trong Excel | File đang mở trong Excel lúc chạy | Đóng file; nếu giao diện báo **Chưa lưu Excel**, đợi lượt chạy thoát hẳn rồi bấm **Lưu lại Excel**. Kết quả vẫn nằm an toàn trong nhật ký |
| Bấm **Stop** mà chưa thoát ngay | Bot chờ lệnh ADB đang chạy (tối đa khoảng 8 giây) và chờ lưu Excel xong | Đợi; đừng đóng cửa sổ khi bot còn đang dừng |
| Bộ cài báo lỗi | App vẫn đang chạy (kể cả biểu tượng dưới khay hệ thống) | Đóng app rồi cài lại |
| `Cap-nhat.bat` không tải được | Mạng hoặc antivirus chặn | Tải tay `SerialPasteBot-Setup.exe` từ trang Releases (xem hướng dẫn cài đặt) |

### Khi lượt chạy bị dừng giữa chừng

Dừng nghĩa là **trên LDPlayer còn một phiên/phiếu đang dở**. Làm theo thứ tự:

1. Đọc hộp thoại báo dừng: nó nêu lý do, đường dẫn **ảnh chụp** lúc dừng và những serial
   đã kịp vào phiên.
2. **Vào app kho, đóng hoặc hoàn tất phiên đang dở.** Không dọn thì mã sau cũng hỏng.
3. Bấm **Start** lại với đúng file và đúng cấu hình cũ. Bot nhận ra lượt trước (nhật ký
   `run_journal.sqlite3`) và hỏi **"Tiếp tục lượt trước?"**: *Yes* là bỏ phần đã xong và
   chạy phần còn lại.
4. Nếu có thao tác bot **chưa biết kết quả** (ví dụ mất điện giữa lúc gõ), bot hiện hộp
   *"Cần đối chiếu thao tác chưa rõ kết quả"* kèm danh sách. Chỉ chọn **Yes** sau khi đã
   kiểm tra trên app; bot sẽ bỏ các mã đang dở, ghi chúng là *chưa xác minh* và chạy tiếp
   phần chưa làm. Chưa chắc thì chọn **Cancel**.
5. Đổi file hoặc cấu hình mà vẫn còn thao tác chưa rõ từ lượt trước, bot báo *"Còn thao
   tác chưa đối chiếu"*. Bấm **Đối chiếu tiến độ**, kiểm tra trên app, rồi mới chạy dữ liệu
   mới.

**Tạm dừng:** bấm **Pause** (hoặc `F9`) thì bot dừng ở *điểm an toàn kế tiếp*, không cắt
ngang giữa một bước. **Stop** là `F10` (khi cửa sổ bot đang được chọn).

### Gửi thông tin để người phát hành xem lỗi

Menu **Công cụ → Mở thư mục log**, gửi file log của lượt vừa chạy kèm ảnh chụp lúc lỗi
(nằm trong `%LOCALAPPDATA%\SerialBot\screenshots`).

---

## 9. Quy tắc an toàn

- **Chạy thử một mã** trước (mục 4).
- **Kiểm lại Mã tote và Mã bin** mỗi khi đổi kho hoặc sang máy mới. Các ô cấu hình nhớ theo
  từng tài khoản Windows, máy mới sẽ về giá trị mặc định.
- **Chỉ một máy ảo, một lượt chạy** tại một thời điểm.
- **Không thao tác tay trên app trong LDPlayer** khi bot đang chạy.
- **Giữ bật Đối chiếu số lượng.**
- **Chỉ tick "Tự tạo phiên check-in nếu chưa có"** khi chắc chắn.
- Bot **không bao giờ tự gửi lại** một lệnh nhập đã mất phản hồi; nó đối chiếu lại bằng bộ
  đếm trên màn hình và dừng nếu không có bằng chứng. Đừng bấm tay bù vào chỗ bot dừng khi
  chưa kiểm tra trạng thái thật trên app.
- Muốn gỡ bot: **Settings → Apps → Serial Paste Bot → Uninstall**. Trình gỡ hỏi có xóa dữ
  liệu cá nhân (log, ảnh, kịch bản, nhật ký) không; định cài lại thì chọn **Không**.

## Tài liệu liên quan

- [`HUONG-DAN-CAI-DAT.md`](HUONG-DAN-CAI-DAT.md): cài đặt chi tiết trên máy mới và các cách cài khác.
- [`../README.md`](../README.md): mô tả đầy đủ mọi chế độ, kể cả chế độ **Từng serial**
  (kiểm kê, mỗi dòng Excel là một serial độc lập) và chạy trên Chrome.
- [`../OPTIMIZATION_NOTES.md`](../OPTIMIZATION_NOTES.md): chi tiết kỹ thuật về xác nhận kết
  quả, nhật ký phục hồi và lưu Excel.
