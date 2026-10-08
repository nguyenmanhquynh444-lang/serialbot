# Bot Kiểm Đếm Serial - LDPlayer Automation

Ứng dụng desktop (PyQt6) tự động đọc serial từ file Excel và nhập lần lượt vào app trên LDPlayer qua ADB, xác nhận kết quả thật, ghi lại kết quả và báo cáo.

Đợt cập nhật tính đúng, phục hồi SQLite và tối ưu LDPlayer: xem [hướng dẫn triển khai và đo trước–sau](OPTIMIZATION_NOTES.md). Đường nhanh phân biệt kết quả đã xác nhận với kết quả chưa phát hiện lỗi.

Có **ba kiểu chạy**, chọn ở ô "Kiểu chạy" đầu trang Cấu hình:

| Kiểu chạy | Đơn vị công việc | Dùng khi |
|---|---|---|
| **Từng serial** (mặc định) | Mỗi dòng Excel là một serial độc lập | Kiểm đếm, tra cứu — dòng này lỗi thì bỏ qua, chạy tiếp dòng sau |
| **Theo mã OR** | Mỗi mã OR là một phiên lấy hàng | Xuất kho — xem [Chế độ xuất kho theo mã OR](#chế-độ-xuất-kho-theo-mã-or) |
| **Theo mã check-in** | Mỗi mã check-in là một phiếu nhập | Nhập hàng — xem [Chế độ nhập hàng theo mã check-in](#chế-độ-nhập-hàng-theo-mã-check-in) |

Và **hai đích chạy**, chọn ở ô "Chạy trên" ngay trên đó: `LDPlayer (app Android)` như từ trước tới nay, hoặc `Chrome (trang web)` để bot bấm thẳng trên bản web của hệ thống kho — xem [Chạy trên trình duyệt](#chạy-trên-trình-duyệt-chrome).

Hai chế độ chạy theo phiên dùng **cùng một kiểu file Excel** (một cột mã + cột serial) và cùng một bộ quy tắc an toàn (dừng cả lượt khi gặp bất thường, không bỏ qua dòng).

## Cài đặt

```bash
pip install -r requirements.txt
```

> Chế độ chạy trên trình duyệt cần thêm `playwright` (đã có trong `requirements.txt`). **Không** cần chạy `playwright install`: bot gắn vào Chrome sẵn có trên máy chứ không tải trình duyệt riêng.

> Chạy trên **Windows**. Cần LDPlayer đã cài (dùng `ldconsole.exe`/`adb.exe` đi kèm) để dùng ADB input/verify; nếu không có, bot tự chuyển sang gõ bàn phím qua `pyautogui`/`pygetwindow`.

### Bot tìm LDPlayer ở đâu

Không cần cài LDPlayer đúng một chỗ cố định. Thứ tự dò, chắc chắn dần:

1. Biến môi trường `LDPLAYER_DIR` — nếu đặt thì dùng luôn, không đoán tiếp.
2. Registry (mục Gỡ cài đặt Windows ghi khi cài LDPlayer).
3. Các chỗ cài quen thuộc trên ổ `C:`, `D:`, `E:` — `\LDPlayer\LDPlayer9`, `\Program Files\LDPlayer\LDPlayer9`, …
4. Riêng `adb.exe`: tra thêm `PATH`, nên máy có Android SDK riêng cũng chạy được.

Máy nào cài chỗ lạ thì đặt biến môi trường rồi mở lại app:

```bash
setx LDPLAYER_DIR "D:\Games\LDPlayer\LDPlayer9"
```

**Chế độ xuất kho chỉ chạy qua ADB** (không có đường lui gõ bàn phím — gõ nhầm cửa sổ giữa một phiên pick là hỏng đơn thật), nên không tìm thấy `adb.exe` là không chạy được gì. Gặp lỗi kết nối, app sẽ nói thẳng có phải do thiếu `adb.exe` hay không.

## Chạy ứng dụng

```bash
python main.py
```

## Tính năng chính

- **Chạy trên trình duyệt** — gắn vào Chrome đang mở và bấm bằng chính DOM: tự cuộn tới nút, tự chờ nút hết bị che và hết `disabled` rồi mới bấm, nên hết cảnh bấm trượt như bấm theo tọa độ; xem mục [Chạy trên trình duyệt](#chạy-trên-trình-duyệt-chrome).
- **Nhập liệu qua ADB** (khuyến nghị) — gõ thẳng vào app, không cần focus cửa sổ LDPlayer. Có thể chọn bàn phím khi ADB không sẵn sàng trước lượt chạy; không tự gửi lại thao tác đã mất phản hồi.
- **Background mode** — bật khi bạn muốn **vừa chạy bot vừa dùng máy làm việc khác**. Ở chế độ này bot chỉ dùng ADB và **không bao giờ** chuyển sang gõ bàn phím, nên không có nguy cơ gõ nhầm serial vào cửa sổ bạn đang làm. Nếu ADB lỗi, bot dừng và báo lỗi. LDPlayer có thể minimize hoặc nằm sau cửa sổ khác.
- **Xác nhận kết quả thật** qua `uiautomator` — phân loại từng serial là `OK` / `ERROR` / `UNKNOWN` dựa trên từ khóa lỗi/thành công cấu hình được, thay vì mặc định "gõ xong là thành công".
- **Gặp hộp thoại lỗi thì tự bấm OK và chạy tiếp** — đọc nội dung hộp thoại trước, ghi lại, rồi mới bấm; xem mục [Khi app báo lỗi](#khi-app-báo-lỗi).
- **Chờ theo tín hiệu, không chờ theo đồng hồ** — bot gõ dòng tiếp theo ngay khi app trả lời xong, và từ chối chấm điểm một dòng bằng màn hình vẫn đang là kết quả của dòng trước; xem mục [Tốc độ](#tốc-độ-và-chuyện-app-chưa-kịp-ghi-nhận).
- **Chụp ảnh màn hình** khi lỗi/không rõ để có bằng chứng.
- **Ghi kết quả ngược vào Excel** — thêm một sheet `Ket qua <timestamp>` vào **chính file nguồn** (không tạo file nào khác), gồm Hàng Excel/Serial/Trạng thái/Phản hồi app/Thời gian/Lý do/Ảnh chụp, lưu định kỳ để không mất dữ liệu nếu crash. Mỗi lần chạy một sheet riêng; sheet dữ liệu gốc không bị chạm ô nào.
- **Export Report** — file Excel riêng gồm 4 sheet: Summary (tổng/thành công/lỗi/không tìm thấy/tỉ lệ/tốc độ), Chi tiết, Lỗi, Không tìm thấy.
- **Preview & validate** trước khi chạy — xem trước danh sách, cảnh báo serial trùng lặp, bỏ chọn từng dòng.
- **Dry-run** — chỉ chạy thử N serial đầu để kiểm tra cấu hình.
- **Nhật ký SQLite/Resume** — khớp đúng dữ liệu, sheet, mode và cấu hình; giữ kết quả dù Excel chưa lưu. Thao tác chưa rõ kết quả phải đối chiếu trên app trước khi tiếp tục.
- **Retry Errors** — chạy lại riêng các dòng lỗi mà không cần đọc lại Excel.
- **Chạy song song nhiều instance LDPlayer** — tick nhiều instance trong danh sách, serial được chia đều, mỗi instance có thanh tiến độ riêng.
- **Xuất kho theo mã OR** — gộp serial theo mã OR rồi chạy trọn một phiên lấy hàng cho từng mã (tìm phiên → tote → vị trí lấy hàng → quét serial → đóng phiên); xem mục [Chế độ xuất kho theo mã OR](#chế-độ-xuất-kho-theo-mã-or).
- **Nhập hàng theo mã check-in** — cùng kiểu file, vào bằng nút Receive và mỗi mã là một phiếu nhập; xem mục [Chế độ nhập hàng theo mã check-in](#chế-độ-nhập-hàng-theo-mã-check-in).
- **Dán mã sản phẩm cố định trước mỗi serial** — màn hình nhận hàng chờ xen kẽ *mã sản phẩm → serial → mã sản phẩm → …*; điền mã một lần, bot nhớ và tự gõ lại trước từng serial, kèm lớp chặn khi app từ chối mã; xem mục [Dán mã sản phẩm cố định trước mỗi serial](#dán-mã-sản-phẩm-cố-định-trước-mỗi-serial).
- **Lưu/khôi phục cấu hình theo profile** (QSettings) — tự nhớ cấu hình lần chạy trước.
- **Tự nạp sheet + tự đoán cột serial** theo header (`Serial`, `Seri`, `IMEI`...).
- **Hotkey** F9 = Pause/Resume, F10 = Stop (khi cửa sổ app đang có focus).
- **ETA + tốc độ xử lý** hiển thị trên progress bar.
- **Lọc/tìm kiếm trong log**, thông báo (beep + tray) khi chạy xong.
- **Log ra file** trong `logs/run_*.log` để xem lại lịch sử.

## Chế độ xuất kho theo mã OR

Chọn **Kiểu chạy → "Theo mã OR (xuất kho)"**. Khung *Xuất kho theo mã OR* hiện ra ở trang Cấu hình.

Khác biệt cốt lõi so với chế độ thường: **đơn vị công việc là mã OR, không phải serial**. Một mã OR gồm một hoặc nhiều serial và chúng phải vào đúng một phiên lấy hàng — quét lẫn sang phiên khác là xuất kho nhầm đơn. Vì thế mọi bước đều xác nhận đang đứng đúng màn hình rồi mới gõ, và **gặp bất thường là dừng cả phiên chạy** chứ không "bỏ qua dòng này rồi đi tiếp".

> **Mã OR chứ không phải mã vận đơn.** Ô tìm kiếm của màn hình *Lấy hàng* ghi rõ "Tìm theo mã OR", và thẻ phiên lọc ra **không in mã vận đơn lẫn mã OR** lên đâu cả. Cột MVĐ trong file vẫn được mang theo, nhưng chỉ để ghi vào kết quả và báo cáo — bot không gõ nó vào ô nào.

### Chuẩn bị file Excel

Ba cột — mã OR, mã vận đơn (MVĐ), serial — kèm một **dòng tiêu đề** ở trên cùng.

| | A — OR | B — MVĐ | C — Seri |
|---|---|---|---|
| 1 | *OR* | *MVĐ* | *Seri* |
| 2 | ORVINEKGK4T1560 | 581PIPTE03082026 | E52771260715N01954 |
| 3 | ORVINT8L5UY9235 | 580PIPTE03082026 | E52771260715N01854 |
| 4 | ORVINGX4X24Z597 | 586PIPTE03082026 | E52771260715N02500 |

→ 3 phiên lấy hàng, mỗi phiên 1 serial.

Mã OR có thể **lặp lại từng dòng** khi một OR có nhiều serial, hoặc để **ô gộp** trải trên nhiều dòng — bot đọc được cả hai (openpyxl chỉ trả giá trị ở dòng trên cùng của vùng gộp, nên bot tự kéo xuống).

Mở file xong, bot **tự điền ba ô cột** theo dòng tiêu đề: tiêu đề đúng bằng `OR` thành cột mã OR, tiêu đề kiểu `MVĐ` / `Ma van don` / `Bill` thành cột MVĐ, tiêu đề kiểu `Serial` / `Seri` / `IMEI` thành cột serial. File hai cột đời cũ (không có tiêu đề `OR`) vẫn chạy được: cột mã vận đơn lùi về làm mã tìm phiên như trước, cột MVĐ để trống.

> Dòng tiêu đề không bắt buộc, nhưng nên có: không có nó thì phải đặt Start row = 1. Kết quả đi vào một sheet riêng nên không còn chuyện ghi đè lên dữ liệu, và cột ngay sau cột serial cũng dùng thoải mái.

### Cấu hình

Bốn ô dưới đây **cố định cho cả lượt chạy**: đặt xong rồi bấm Start, muốn đổi thì dừng rồi chạy lại — phiên đang dở trên máy ảo mới là thứ quyết định tote/vị trí nào đang hợp lệ.

| Ô | Mặc định | Ý nghĩa |
|---|---|---|
| **Cột mã OR** | `A` | Cột chứa mã bot gõ vào ô *Tìm theo mã OR* (đọc được cả ô gộp). Tự điền theo tiêu đề khi mở file |
| **Cột MVĐ** | `B` | Mã vận đơn đi kèm. Bot **không gõ** mã này vào đâu — nó chỉ đi vào file kết quả và sheet báo cáo để tra ngược về đơn hàng. Để trống nếu file không có cột này |
| **Serial column** | `H` | Dùng chung với chế độ thường, cũng tự điền theo tiêu đề. Phải khác hai cột trên, trùng là báo lỗi ngay |
| **Start row / End row** | `2` / trống | Như chế độ thường |
| **Mã tote** | `T001` | Mã thiết bị chứa hàng, gõ ở màn hình *Quét thiết bị chứa hàng* |
| **Mã bin** | `PYTES` | Vị trí lấy hàng, gõ ở màn hình *Quét vị trí lấy hàng*. Điền giá trị là **ép cứng**: app chỉ sang vị trí khác thì bot dừng chứ không lấy nhầm kệ. Để trống thì bot đọc vị trí app đang yêu cầu rồi gõ lại — dùng khi đơn trải nhiều vị trí |
| **Đối chiếu số lượng** | bật | So số sản phẩm app báo (*SL sản phẩm* trên thẻ) với số serial trong Excel, lệch là dừng **trước khi mở phiên** — lúc đó chưa động gì tới kho. Tắt đi thì sai số chỉ lộ ra khi đã quét dở dang |

Các ô không dùng ở chế độ này bị **khóa kèm tooltip** (chứ không ẩn, để khỏi tưởng app thiếu tính năng): Enter mode, Wait before Enter, ba ô từ khóa, Kịch bản thao tác, Background mode, Verify result, Dry-run.

> **Chỉ chạy trên MỘT máy ảo.** Một phiên lấy hàng là một tài khoản đang thao tác kho; chia ra nhiều instance là xuất nhầm đơn. Bot lấy instance đầu tiên bạn tick.

### Bot làm gì trong một mã OR

1. **Về màn hình tìm mã OR.** Đang ở menu chính thì bấm *Lấy hàng* (`btnPick`); đang đứng sẵn ở màn hình tìm thì dùng luôn — từ mã thứ hai trở đi luôn là trường hợp này.
2. **Tìm mã OR** — xóa ô rồi gõ mã, chờ danh sách lọc xong. Chỉ bấm vào khi lọc ra **đúng một** thẻ; ra 0 hay 2+ thẻ là dừng, không dám đoán.
3. **Đối chiếu số lượng** (nếu bật) rồi mới bấm *Lấy hàng* trên thẻ.
4. **Đóng hộp "Picking assistant"** nếu app hiện — hộp chọn ngôn ngữ. Bot bấm nút nghịch của AlertDialog (`button2`) chứ không khớp chữ "Skip", vì màn hình quét serial cũng có nút tên Skip nhưng nó là "bỏ qua sản phẩm này". Hộp thoại **lạ** thì dừng, không bấm bừa.
5. **Quét thiết bị chứa hàng (tote)** — trừ khi số đếm *"Số lượng thiết bị chứa hàng cần DK"* đã đủ; app nhớ tote giữa các phiên nên từ mã thứ hai màn hình này thường chỉ lướt qua, gõ thêm là đăng ký chồng một thiết bị nữa.
6. **Quét vị trí lấy hàng (bin)** — đối chiếu với *"Vị trí lấy hàng kế tiếp"* app đang chỉ.
7. **Quét từng serial** — sau mỗi serial, bot chờ **số đếm `0/10` tăng đúng một đơn vị** rồi mới gõ dòng sau. Đây là bằng chứng app đã nhận, chắc chắn hơn hẳn kiểu "gõ xong coi như xong". Serial cuối cùng app đóng phiên nên không còn số đếm — lúc đó hộp thoại kết thúc chính là dấu hiệu xong.
8. **Đóng phiên** — bấm OK trên hộp *"Công việc lấy hàng đã kết thúc"*, chờ về lại màn hình tìm mã OR rồi mới sang mã tiếp theo. Sau serial cuối app còn chèn hộp *"Vị trí cần đặt sản phẩm vừa lấy"*, nên bước này bấm được nhiều hơn một lần.

Mỗi bước chờ tối đa 15s theo **dấu hiệu trên màn hình**, không ngủ cứng. Tiến trình từng bước hiện ở thanh trạng thái (`[ORVIN...] 3/10 quét SN0003`).

> Bot khớp phần tử theo **resource-id** chứ không theo chữ, vì app có nút đổi ngôn ngữ — máy này chạy tiếng Anh máy kia tiếng Việt, khớp chữ là hỏng. App của bạn dùng id khác thì sửa các hằng `RID_*` ở đầu [pick_runner.py](pick_runner.py).

### Hai lớp chặn khi mở phiên

Thẻ phiên **không in mã OR** lên đâu cả — nó chỉ có mã phiên (`PL260804PTD2T_PTD_581`), nhãn "VIN" và số lượng. Nên không đối chiếu được mã trên thẻ như luồng nhập hàng, và bot dựa vào hai thứ khác:

| Lớp chặn | Bắt được gì |
|---|---|
| Lọc ra **đúng một** thẻ | Mã mơ hồ khớp nhiều phiên — bấm cái nào cũng có thể là nhầm đơn |
| **Ô tìm kiếm phải đang giữ đúng mã bot vừa gửi** | Lệnh gõ qua ADB hụt hoặc thừa ký tự. Mã cụt vẫn lọc ra một thẻ trông rất bình thường — của đơn khác. Ô nào không trả về text thì bỏ qua lớp này chứ không chặn, vì không đọc được không có nghĩa là sai |

Còn một lớp nữa ở bước quét vị trí: **app chỉ sang kệ khác với ô "Mã bin" là dừng**, không gõ đại. Muốn đi theo app thì để trống ô đó.

### Xem trước & cảnh báo

Bấm Start sẽ mở hộp **Xem trước - chạy theo mã OR**: bảng mã OR / MVĐ / số serial / dòng Excel, tick bỏ từng mã, và **cảnh báo nằm ngay trên đầu** — đây là chỗ duy nhất bạn nhìn thấy dữ liệu bẩn trước khi bot động vào kho thật.

| Tình huống | Bot làm gì |
|---|---|
| Cột mã OR trùng cột serial, hoặc cột MVĐ trùng cột serial | Báo lỗi, không chạy |
| **Cột mã OR trỏ nhầm vào một cột serial** | Cảnh báo *"nhiều khả năng trỏ nhầm"* — file kiểu này đọc trơn tru và hiện ra một đống mã trông như thật, không cảnh báo thì tới lúc bot tìm phiên mới chết |
| Serial nằm phía trên mã OR đầu tiên | Bỏ qua dòng đó + cảnh báo (không gán bừa vào mã nào) |
| Serial trùng nhau | Cảnh báo kèm số dòng của cả hai |
| Một mã OR tách thành hai cụm rời | Cảnh báo — rất dễ là file bị sắp lẫn, mà chạy tiếp thì thành hai phiên riêng |
| Một mã OR mang hai MVĐ khác nhau | Cảnh báo — báo cáo chỉ giữ được mã đầu tiên |
| Dòng trống xen giữa | Bỏ qua, không cắt nhóm |

### Khi phải dừng giữa chừng

Dừng nghĩa là **trên LDPlayer còn một phiên lấy hàng đang dở** — phải đóng hoặc hoàn tất phiên đó rồi mới chạy lại được, nếu không mã sau cũng hỏng. Bot nói thẳng điều này trong hộp thoại báo dừng, kèm:

- **Ảnh chụp màn hình** lúc dừng (đường dẫn ghi trong hộp thoại).
- **Những serial đã kịp vào phiên**, ghi với lý do `Đã xuất trước khi dừng` — để biết phiên dở tới đâu mà dọn.
- **Checkpoint** các mã OR đã xong trọn vẹn. Lần chạy sau bot hỏi *"Lần trước đã xong N mã OR — bỏ qua và chạy tiếp phần còn lại?"*; chọn No là chạy lại từ đầu.

**Tạm dừng** ở chế độ này chỉ có hiệu lực ở điểm an toàn kế tiếp (hết mã OR đang chạy, hoặc hết serial đang quét), không cắt ngang giữa một bước: dừng giữa một phiên lấy hàng không có trạng thái nào an toàn để treo lại.

Luồng này **chỉ chạy qua ADB**, không có đường lui gõ bàn phím như chế độ thường — gõ nhầm vào cửa sổ Windows giữa một phiên là hỏng đơn thật, nên thà không chạy. ADB không phản hồi thì bot báo lỗi ngay từ đầu.

### Kết quả và báo cáo

Vẫn ghi ngược vào sheet `Ket qua <timestamp>` của chính file nguồn như chế độ thường. Bấm **Export Report** ra một file riêng 4 sheet — đây là chỗ duy nhất app tạo file mới, và chỉ khi bạn tự bấm:

| Sheet | Nội dung |
|---|---|
| **Summary** | Tổng hợp phiên chạy |
| **Ma OR** | Mã OR, mã vận đơn (MVĐ), mã phiên, cần xuất, đã xuất, trạng thái, thông báo |
| **Chi tiet** | Từng serial |
| **Loi** | Chỉ các dòng không OK |

Cột **MVĐ** chỉ xuất hiện khi file nguồn có khai cột đó — báo cáo của luồng nhập hàng không phải gánh thêm một cột luôn rỗng.

Sheet **Ma OR** tính lại trạng thái từ số lượng thực xuất chứ không tin cột status: xuất thiếu mà vẫn ghi `OK` thì người đọc báo cáo không biết còn phiên đang dở.

## Chế độ nhập hàng theo mã check-in

Chọn **Kiểu chạy → "Theo mã check-in (nhập hàng)"**. Cùng kiểu file Excel như chế độ xuất kho, chỉ khác: **cột A là mã check-in** thay vì mã OR, và không có cột MVĐ. Khung cấu hình tự đổi tên nhãn theo chế độ đang chọn, đồng thời khóa các ô Cột MVĐ / Mã tote / Mã bin.

| | A — Ma check-in | B — Serial |
|---|---|---|
| 1 | *Ma check-in* | *Serial* |
| 2 | CKSIRVIN89HN210210 | E52771260430D01999 |
| 3 | CKSIRVIN89HN210210 | E52771260509N00734 |
| 4 | CKSIRVIN9NWS373102 | E52771260412D01939 |

Điền **mã check-in** (`CKSIRVIN89HN210210`), **mã nhập kho** (`IRVIN89HN210`) hay **mã yêu cầu** (`167PIVGR27072026`) đều được — ô tìm kiếm của app nhận cả ba, và bot đối chiếu `tvSessionCode` lẫn `tvAddInfo` trên thẻ.

### Bot làm gì trong một phiếu

1. **Bấm Receive / Nhận hàng** ở menu chính (`btnOpenReceive`) để vào *Danh sách check-in*.
2. **Gõ mã + Enter** vào ô tìm kiếm. Enter là đủ để app tra — ô tìm kiếm có nút **CHECKIN** nhưng bot không cần bấm tới.
3. Rồi tùy app đưa đi đâu:
   - **Hiện thẻ** → chờ lọc còn **đúng một** thẻ khớp rồi bấm "Nhận hàng" (`btnStart`). Ra 0 hay nhiều hơn 1 là dừng — màn hình chưa lọc có 6 thẻ, bấm bừa thẻ đầu là mở nhầm phiếu của người khác.
   - **Vào thẳng phiên** → không còn gì để bấm, bot quét tiếp luôn.
   - **Hỏi tạo phiên** → xem [Khi mã chưa có phiên check-in](#khi-mã-chưa-có-phiên-check-in).
4. **Đối chiếu số lượng** ngay khi màn hình quét hiện ra: thẻ check-in không có ô số lượng như thẻ picking, nên chốt chặn duy nhất là tổng của `0/N`. Lệch với số serial trong Excel là dừng — lúc đó chưa quét serial nào.
5. **Quét từng serial**, chờ số đếm tăng đúng một đơn vị sau mỗi lần, giống hệt luồng xuất kho.
6. **Đóng phiếu**, chờ về lại danh sách check-in (hoặc menu chính — bot đỡ cả hai) rồi mới sang phiếu tiếp theo.

Không có bước quét tote/bin, nên hai ô đó bị khóa ở chế độ này.

### Khi mã chưa có phiên check-in

Gõ một mã nhập kho chưa từng check-in, app hiện hộp thoại:

> Yêu cầu nhập kho chưa có tạo phiên check-in? Bạn có muốn tạo phiên và nhận hàng
> **[ Quay lại ]  [ Xác nhận ]**

Bấm **Xác nhận** là **tạo một phiên check-in thật** trong hệ thống — không phải chỉ mở màn hình. Nên mặc định bot **bấm "Quay lại" rồi dừng**, báo rõ mã nào chưa có phiên để bạn tự quyết.

Tick **"Tự tạo phiên check-in nếu chưa có"** trong khung cấu hình để bot tự bấm Xác nhận. Chỉ bật khi biết chắc mọi mã trong file đều cần tạo phiên mới — bật nhầm là tạo ra một loạt phiên rác phải đi dọn.

> Hộp thoại này là loại **app tự vẽ**, không phải `AlertDialog` chuẩn của Android: nút thuận tên `btnAccept` chứ không phải `button1`, và uiautomator chỉ dump được cửa sổ hộp thoại chứ không kèm danh sách phía sau. Đó là lý do nó có đường xử lý riêng thay vì dùng lại đường của luồng pick.

> **Phần chưa dò hết:** các màn hình *sau* nút "Nhận hàng" chưa được dump trên máy thật — bấm vào là mở một phiếu nhập thật. Bot đang chạy theo giả thiết bấm xong là vào thẳng màn hình quét serial. Nếu app chèn thêm bước (quét thùng, chọn sản phẩm…), bot **dừng và liệt kê những gì đang hiện trên màn hình** thay vì gõ serial vào ô lạ. Dán nguyên thông báo đó vào là bổ sung được bước còn thiếu mà không phải dò lại từ đầu.

### Kết quả

Giống chế độ xuất kho, chỉ khác sheet **Check-in** (thay cho **Ma OR**) trong Export Report, cột đầu là `Ma check-in` và không có cột MVĐ.

## Dán mã sản phẩm cố định trước mỗi serial

Dùng khi bạn **tự mở sẵn màn hình nhận hàng** trên LDPlayer rồi để bot gõ — tức chế độ **Từng serial**, không phải chế độ theo mã check-in.

Màn hình quét của app dùng **chung một ô** cho hai thứ, chờ xen kẽ nhau:

```
mã sản phẩm → Enter → serial → Enter → mã sản phẩm → Enter → serial → ...
```

Cả file thường chỉ có **một mã sản phẩm**, nên điền nó vào ô **"Mã sản phẩm cố định"** (khung *Nhận hàng: dán mã sản phẩm trước mỗi serial*, chỉ hiện ở chế độ Từng serial). Bot nhớ đúng một mã cho cả lượt chạy và tự gõ lại trước từng serial — file Excel vẫn chỉ cần cột serial như cũ. **Để trống là chạy y như trước**: mỗi dòng chỉ gõ serial.

### Hai chỗ nguy hiểm và cách bot chặn

| Tình huống | Nếu không chặn | Bot làm gì |
|---|---|---|
| App **từ chối mã sản phẩm** (sai mã, sai kho, hết hạn) | Serial gõ tiếp rơi vào hộp thoại, Enter đóng luôn nó → dòng đó được ghi **OK** trong khi **không có gì vào kho** | Soi cửa sổ ngay sau mã sản phẩm, thấy hộp thoại thì chấm dòng đó là lỗi kèm câu app báo, **không gõ serial**, đóng hộp thoại rồi chạy dòng sau |
| Hộp thoại của dòng **trước** hiện muộn, đúng lúc sắp gõ mã sản phẩm | Kết luận bị gán nhầm sang dòng đang chạy, dòng kia được OK oan | Đọc hộp thoại, gán về **đúng dòng đã gõ ra nó**, đóng lại rồi gõ mã sản phẩm + serial của dòng này |

Bot **không** gộp mã sản phẩm và serial vào một lệnh ADB, dù gộp thì nhanh hơn: gộp là serial đi ra bất kể hộp thoại vừa bật lên vì mã sản phẩm.

### Ô "Chờ sau mã sản phẩm (s)" — mặc định 0.5s

Đây là **khoảng chờ cứng duy nhất còn lại** trong một dòng, và nó buộc phải cứng: app đổi ý nghĩa ô nhập theo trạng thái bên trong chứ không đổi màn hình, nên không có dấu hiệu nào rẻ để soi (chỉ dump cả cây view ~1200ms mới thấy tên sản phẩm hiện ra — đắt hơn chính khoản chờ). Gõ serial sớm quá thì nó **bị đọc thành mã sản phẩm**.

- Thấy serial bị báo "không tìm thấy" hàng loạt → **tăng** lên 0.8–1.0s.
- App phản hồi nhanh, chạy vài trăm dòng không lỗi → **giảm** dần xuống 0.3s.
- Đặt 0 thì vẫn còn một lần soi cửa sổ (~130ms) làm nhịp nghỉ tối thiểu.

### Bot chặn không cho chạy khi

- **Confirm key** đang để *"No Enter (paste only)"* — mã sản phẩm sẽ nằm lại trong ô và serial nối vào sau nó.
- Đang chọn một **kịch bản** — kịch bản tự định nghĩa chuỗi thao tác nên đi đường riêng, ô mã sản phẩm bị bỏ qua. Chọn kịch bản "Mặc định", hoặc tự thêm bước *Gõ chữ* cho mã sản phẩm vào chính kịch bản đó.

## Tốc độ và chuyện "app chưa kịp ghi nhận"

Hai việc này là một: chỉ được bỏ các khoảng chờ cứng nếu bot thật sự **biết** app đã xử lý xong serial vừa gửi. Nên bot chờ theo tín hiệu chứ không chờ theo đồng hồ.

**Một dòng chạy trót lọt tốn tiền ở ba chỗ** — đo trên 758 dòng log máy thật, trung bình ~2700ms:

| Chặng | Tốn | Là gì |
|---|---|---|
| Soi cửa sổ trước khi gõ | ~130ms | một lượt đi-về ADB để biết màn hình còn sạch |
| Lệnh gõ | ~1670ms | mỗi lần gọi `input` là một lần máy ảo dựng tiến trình Java |
| Chờ hộp thoại lỗi hiện ra | ~870ms | khoản chờ chết, dòng nào cũng gánh |

**Bớt việc cho mỗi serial**

| | Trước | Giờ |
|---|---|---|
| Số lệnh ADB / 1 serial lỗi | 6 | **4** |
| Số lần gọi `input` (mỗi lần = 1 lần máy ảo dựng tiến trình Java) | 5 | **2** |
| Số lượt đi-về ADB / 1 serial trót lọt | 2 | **1** |
| Ngủ cứng mỗi serial | 0.2s + 0.3s + delay | **0** |
| Chờ hộp thoại lỗi | 0.8s | **0.35s** |
| Đọc màn hình | ghi ra `/sdcard` rồi `cat` đọc lại | đổ thẳng ra `stdout` |

- **Xóa ô + gõ serial + Enter gộp thành một lệnh ADB.** Các keycode xóa ô cũng gộp trong một lần gọi `input` thay vì ba. Máy ảo đời cũ không nhận cú pháp gộp thì bot tự phát hiện và quay về cách cũ, không báo nhầm là mất kết nối.
- **Enter gộp luôn vào chuỗi gõ.** Bảng ký tự bàn phím ảo của Android (`/system/usr/keychars/Virtual.kcm`) khai báo `key ENTER { base: '\n' }`, nên một ký tự xuống dòng cuối chuỗi `input text` chính là phím Enter — bớt hẳn một lần dựng tiến trình Java. Lối này chỉ bật sau khi bot **nhìn tận mắt** một dòng: gõ xong mà serial còn nằm nguyên trong ô nhập nghĩa là máy ảo dịch hụt, bot bấm Enter bù rồi quay về cách cũ cho cả phiên. Và chỉ dò khi đã biết app tự dọn ô sau mỗi lần quét — app không tự dọn thì dấu hiệu đó vô nghĩa, mà đoán bừa rồi bấm Enter bù là quét thành hai lần.
- **Việc soi cửa sổ đi chung một lệnh với việc gõ.** Không chỉ bớt một lượt đi-về: tách làm hai lượt thì giữa chúng có kẽ hở ~130ms, hộp thoại lọt đúng vào đó là serial gõ ra rơi vào hộp thoại còn Enter bấm luôn nút mặc định để đóng nó — serial biến mất mà cả dòng này lẫn dòng trước đều được ghi là thành công. Đi chung một lệnh thì kẽ hở còn vài ms.
- **`Delay per serial` mặc định là 0.** Không cần delay cứng "cho chắc" nữa; chỉ tăng nếu muốn cố tình chạy chậm lại.
- Đặt `Wait before Enter` > 0 sẽ tách lệnh gõ ra làm hai lượt — chỉ dùng khi app cần thời gian nhận đủ chữ trước lúc Enter.
- Ba dòng đầu mỗi phiên được gõ kèm mốc thời gian từng chặng, ghi vào log dạng `Row 4 input stages: xoa=605ms go+enter=1210ms`. Muốn biết thời gian đi đâu thì mở log ra xem, khỏi đo từ ngoài vào.

**Nhớ sang phiên chạy sau những gì đã dò được**

Đường nhanh — hỏi cửa sổ đang focus (~130ms) thay vì dump cả cây view (~1330ms) — chỉ mở sau khi bot **tận mắt thấy** một hộp thoại làm đổi cửa sổ focus. Mà bằng chứng đó chỉ có khi gặp lỗi thật: phiên nào chạy sạch thì đường nhanh nằm im suốt phiên.

Log 21/08 là đúng một phiên như thế — 502 dòng, 0 lỗi, nhịp **2.33s** mỗi dòng, trong khi những phiên gặp lỗi sớm chạy **1.78s**. Nửa giây mỗi dòng, chỉ vì câu trả lời không sống qua nổi lúc đóng chương trình.

Nên nó được ghi ra `device_profile.json` trong thư mục dữ liệu, và phiên sau nạp lại ngay từ dòng đầu. Khóa nhớ là **tên máy ảo + package + versionCode của app**: app cập nhật là mọi kết luận về cách nó vẽ hộp thoại đều hết hiệu lực (bản mới có thể tự vẽ hộp thoại kiểu Flutter, lúc đó cửa sổ focus không đổi và tin theo bản cũ là **mọi dòng đều "OK" mà chẳng ai đọc màn hình**). Không đọc được versionCode thì bot không nhớ và cũng không đọc — thà chậm còn hơn tin nhầm.

**Không chấm dòng này bằng kết quả của dòng trước**

Sau khi gửi serial, bot chờ tới khi màn hình **đúng là kết quả của serial vừa gửi**, rồi mới chấm và gõ dòng tiếp theo:

- App in lại mã vừa quét (như hộp thoại "Mã vừa quét: BSS-...") → bot đối chiếu với mã nó vừa gửi. Khớp thì đi tiếp ngay lập tức; đây cũng là bằng chứng ký tự gửi đi không bị sai lệch.
- Màn hình vẫn còn mã của serial **trước** → biết chắc app chưa xử lý xong, bot chờ tiếp tới `Chờ app phản hồi tối đa` (mặc định 3s). Hết giờ mà vẫn vậy thì dòng đó ghi `UNKNOWN` kèm lý do — thà báo không rõ còn hơn chép kết quả dòng trên xuống dòng dưới, vì kiểu sai đó nhìn file kết quả không tài nào phát hiện.
- Chưa thấy dấu hiệu gì và app vốn hay im lặng → đi tiếp luôn, không chờ. Chỉ những app đã từng cho thấy nó có trả lời mới được chờ thêm.

Hộp thoại lỗi cũng vậy: bot chờ tới khi nó **đóng hẳn** rồi mới gõ serial sau, thay vì ngủ 0.3s rồi hy vọng.

**Hộp thoại tới muộn**

554 mẫu đo trên máy thật: hộp thoại hiện sau 197ms (một nửa số lần), 310ms (75%), 424ms (90%), 495ms (95%) — nhưng có mẫu tới 3.7s. Chờ đủ cho cái đuôi đó là cộng hơn một giây vào **từng dòng** để phòng một phần trăm, nên bot chỉ chờ 0.35s rồi đi tiếp.

Con số 0.35s tính theo tỷ lệ thật: trong 5421 dòng log chỉ ~10% có hộp thoại. Mỗi dòng bớt được 150ms chờ chết, đổi lại ~2% số dòng rơi vào lưới bắt hộp thoại muộn (mỗi lần tốn thêm ~1.5s) — vẫn lãi hơn 100ms mỗi dòng, và lưới đó chấm đúng dòng chứ không bỏ sót.

Phần đuôi do lưới ở đầu dòng sau đỡ: trước lúc gõ, bot thấy màn hình không còn là màn hình sạch thì **đọc hộp thoại đó, gán kết luận về đúng dòng đã gõ ra nó, đóng lại, rồi gõ tiếp dòng hiện tại**. Vì thế kết quả mỗi dòng được giữ lại một nhịp trước khi ghi ra — chỉ khi dòng sau xác nhận màn hình vẫn sạch thì dòng trước mới thành OK chính thức. Bản trước bỏ qua dòng hiện tại rồi dừng cả phiên chạy sau ba lần như vậy.

Nếu màn hình đổi khác mà **không phải hộp thoại** (người dùng chuyển sang màn hình khác, app tự đi chỗ khác) thì bot không gõ mù: dòng đó ghi `UNKNOWN` kèm lý do.

> Nếu app im lặng khi thành công (không hiện gì), mỗi dòng OK tốn thêm tối đa 0.6s để chắc chắn. Điền **Success keywords** để bot nhận ra ngay, hoặc giảm `Chờ app phản hồi tối đa` xuống 0 nếu chấp nhận bỏ lớp bảo vệ này.

## Khi app báo lỗi

> Mục này nói về chế độ **Từng serial**. Chế độ theo mã OR xử lý ngược lại — hộp thoại lạ là dừng cả phiên chạy, xem [Khi phải dừng giữa chừng](#khi-phải-dừng-giữa-chừng).

Sau mỗi serial, bot đọc màn hình rồi xử lý hộp thoại lỗi theo đúng thứ tự này:

1. **Đọc nội dung hộp thoại trước khi bấm gì cả.** Bấm xong là chữ biến mất — mà đó chính là thứ cần ghi vào Excel. Bot lấy nguyên khối hộp thoại: câu lỗi đứng đầu, kèm các dòng chi tiết (mã vừa quét, mã phiên, tài khoản, thời gian) làm bằng chứng, bỏ tiêu đề chung chung như "Lỗi".
2. **Phân loại lý do.** Khớp *Từ khóa không tìm thấy* → lý do `Không tìm thấy serial`; khớp *Error keywords* → `App báo lỗi`; có hộp thoại mà không khớp từ nào → `Hộp thoại lạ`. "Không tìm thấy" luôn được xét trước, nếu không từ khóa lỗi chung sẽ nuốt mất lý do cụ thể.
3. **Bấm nút đóng.** Nhận cả `OK`, `Đồng ý`, `Xác nhận`, `Đóng`, `Close`, `Cancel`, `Hủy`; không thấy nút nào thì gửi Enter.
4. **Kiểm tra lại xem hộp thoại đã đóng thật chưa** rồi mới sang serial tiếp theo — gửi lệnh thành công không có nghĩa là đã đóng. Bot so nội dung màn hình sau khi bấm, nên đúng cả với hộp thoại tự vẽ (Flutter/WebView) vốn không được Android gọi là "dialog".
5. **Ba lần liên tiếp không đóng được thì bot tự tạm dừng** — màn hình đang kẹt, chạy tiếp chỉ tạo ra một loạt dòng bị chấm sai.

Kết quả ghi lại ở bốn chỗ: cột **Trạng thái** (ERROR) và cột **Lý do** trong file Excel kết quả, ô **Không tìm thấy** trên thanh thống kê, dòng log, và sheet riêng **Khong tim thay** trong Export Report — đó là danh sách mang đi tra lại, tách khỏi các lỗi chỉ cần chạy lại bot.

> Serial không có trong hệ thống **không** làm dừng phiên chạy: bot bấm OK, ghi lỗi, chạy tiếp serial sau.

Chỉnh danh sách từ khóa ở tab **Cấu hình** (ô *Từ khóa không tìm thấy* và *Error keywords*). So khớp bỏ dấu và không phân biệt hoa thường, nên `khong tim thay` khớp cả `Không Tìm Thấy`. Nhưng so khớp là **nguyên văn**, không hiểu từ đồng nghĩa: app viết "không tìm **được**" mà danh sách chỉ có "không tìm **thấy**" thì dòng đó bị xếp thành `App báo lỗi` chung chung. Mặc định đã có cả hai; app của bạn dùng chữ khác thì thêm vào ô này.

## Tùy chỉnh thao tác (Kịch bản)

Mặc định bot chạy đúng như cũ: xóa ô → gõ serial → Enter → kiểm tra. Nếu app của bạn cần luồng khác, vào tab **Kịch bản** để tự định nghĩa chuỗi bước, rồi chọn kịch bản đó ở ô "Kịch bản thao tác" trong Cấu hình.

Mỗi dòng Excel là một vòng lặp chạy qua toàn bộ các bước.

| Bước | Công dụng |
|---|---|
| Xóa ô nhập | Xóa sạch ô đang focus |
| Gõ chữ | Gõ nội dung, hỗ trợ biến |
| Gửi phím | Enter / Tab / Back / Home / Delete / Search / Escape / mũi tên |
| Chạm tọa độ | Chạm điểm x, y |
| Chạm phần tử | Tìm theo text hoặc resource-id rồi chạm — bền hơn tọa độ |
| Vuốt | Vuốt/cuộn màn hình |
| Chờ cố định | Dừng N giây |
| **Chờ phần tử** | Chờ đến khi phần tử xuất hiện — thay delay cứng, quan trọng nhất khi chạy nền |
| Đọc chữ vào biến | Đọc text màn hình lưu vào biến |
| Kiểm tra kết quả | Quyết định dòng là OK / ERROR / UNKNOWN, ghi lý do và tự bấm OK đóng hộp thoại |
| Ghi ra cột Excel | Ghi giá trị vào cột bất kỳ của dòng hiện tại |
| Chụp màn hình | Lưu ảnh làm bằng chứng |

**Biến dùng được trong mọi ô text:** `{serial}`, `{row}`, `{cell:B}` (ô bất kỳ cùng dòng), `{var:ten}` (từ bước Đọc chữ), `{date}`, `{time}`.

**Khi bước lỗi** — mỗi bước tự chọn: bỏ qua chạy tiếp / đánh dấu dòng là lỗi / dừng cả phiên.

**Hai trợ lý** giúp không phải đoán tham số:
- **UI Inspector** — đọc màn hình LDPlayer, liệt kê mọi phần tử kèm text/resource-id/vùng, chọn một dòng là tự điền vào bước. Ưu tiên resource-id vì nó không đổi khi app đổi ngôn ngữ.
- **Chọn tọa độ** — chụp màn hình, bạn nhấp vào ảnh, app tự quy đổi ra tọa độ thiết bị.

Bảng trên là các bước cho app Android. Chạy trên Chrome thì có thêm một nhóm bước riêng — xem [Chạy trên trình duyệt](#chạy-trên-trình-duyệt-chrome).

Kịch bản lưu thành JSON trong `recipes/`, copy được sang máy khác.

> **Kịch bản chạy chậm hơn chế độ mặc định — đừng chọn nó nếu không cần.** Kịch bản gõ từng bước rời nhau nên không dùng được mấy lối tắt của luồng chạy thường: không gộp xóa-ô + gõ + Enter vào một lệnh, không bỏ lệnh xóa khi app tự dọn ô, không có đường nhanh hỏi cửa sổ thay cho việc dump cả cây view. Đo trên log máy thật cùng ngày 21/08: chế độ mặc định **2.61s** mỗi dòng, cùng công việc đó chạy qua kịch bản **4.16s**. Log mỗi phiên giờ ghi rõ tên kịch bản đang chạy (`Run started: ... recipe=Classic`) để lần sau nhìn ra ngay.

> Khi chạy nền, nên thay các bước "Chờ cố định" bằng "Chờ phần tử". Lúc bạn dùng máy làm việc khác, CPU bị chia sẻ nên app phản hồi chậm hơn — delay cứng sẽ bắt đầu sai, còn chờ phần tử thì tự co giãn.

## Chạy trên trình duyệt (Chrome)

Ngoài app Android trong LDPlayer, bot chạy được thẳng trên bản web của hệ thống kho. Chọn ở ô **Chạy trên** trong Cấu hình: `LDPlayer (app Android)` như cũ, hoặc `Chrome (trang web)`.

### Vì sao bấm trên web đáng tin hơn bấm trên máy ảo

Đường ADB chỉ có một cách bấm: `input tap x y` — gửi một cú chạm vào tọa độ rồi coi như xong. Nó không biết nút có nằm ngoài màn hình không, có bị hộp thoại che không, có đang mờ đi vì chưa bấm được không.

Đường trình duyệt bấm bằng chính DOM. Trước mỗi cú bấm, Playwright tự cuộn phần tử vào tầm nhìn, chờ nó hiện ra, chờ nó hết dịch chuyển, kiểm tra nó không bị thứ gì che và không còn `disabled` — rồi mới bấm. Ba nguyên nhân bấm trượt phổ biến nhất biến mất mà không phải thêm một bước "Chờ cố định" nào.

Khi nút bị lớp phủ che thật, bot hạ xuống gọi `el.click()` ngay trong DOM; hạ tiếp một nấc nữa là bấm ép theo tọa độ. Nấc cuối này **có thể trả về "đã bấm" trong khi chẳng bấm trúng gì** (sự kiện đi tới phần tử nằm trên cùng), nên kịch bản luôn phải có một bước **Chờ phần tử (web)** ngay sau để xác nhận màn hình thật sự đổi — đúng như luồng ADB kiểm tra lại hộp thoại sau khi bấm OK. Log ghi rõ mỗi lần phải hạ nấc.

### Chuẩn bị Chrome (làm một lần)

Bấm **Mở Chrome cho bot** trong khung Trình duyệt. Nút này mở Chrome bằng một **profile riêng** kèm cổng gỡ lỗi.

Phải là profile riêng, không dùng chung với Chrome cá nhân: từ Chrome 136, Chrome từ chối bật cổng gỡ lỗi trên thư mục profile mặc định (chống trang web độc chiếm quyền điều khiển trình duyệt của bạn). Profile của bot nằm ở `%LOCALAPPDATA%\SerialBot\chrome-bot-profile`.

Lần đầu, hãy **đăng nhập hệ thống kho** trong cửa sổ vừa mở rồi mở đúng màn hình cần chạy. Chrome nhớ đăng nhập cho các lần sau.

Ô **Tab chứa** cho biết bot điều khiển tab nào: bot chọn tab có địa chỉ chứa đoạn này (ví dụ `ntl.ops.vnfai.com`). Để trống thì lấy tab đầu tiên — dễ bấm nhầm sang tab khác khi Chrome đang mở nhiều tab.

### Bắt buộc phải có kịch bản

Chế độ trình duyệt **không có luồng "như cũ"**. Luồng mặc định được viết cho màn hình app Android: gõ vào ô đang focus rồi đọc cây view qua ADB. Trên một trang web nó vẫn chạy nhưng không làm đúng việc gì cả, nên bot chặn ngay trước khi đọc Excel thay vì để bạn phát hiện sau vài trăm dòng.

Hai chế độ theo phiên (mã OR, mã check-in) cũng không dùng được: chúng bám sát từng nút của app Android. Chọn Chrome là ô Kiểu chạy tự về `Từng serial` rồi khóa lại.

Trong `recipes/` có sẵn `web-mau.json` để chép ra sửa.

### Các bước dành cho web

| Bước | Công dụng |
|---|---|
| Mở trang web | Chuyển tab hiện tại sang một địa chỉ (dùng được biến: `.../serial/{serial}`) |
| **Điền ô (web)** | Xóa rồi điền thẳng vào ô chỉ định — không cần ô đang được focus |
| **Bấm nút (web)** | Bấm theo CSS selector và/hoặc chữ trên nút |
| Chọn trong danh sách (web) | Chọn một mục của `<select>`, khớp theo value hoặc theo chữ hiển thị |
| **Chờ phần tử (web)** | Chờ phần tử hiện ra / biến mất — thay cho delay cứng |
| Đọc chữ (web) | Đọc chữ của phần tử vào biến để ghi ra Excel |

Ưu tiên CSS selector hơn chữ hiển thị: selector không đổi khi hệ thống đổi nhãn hay đổi ngôn ngữ. Lấy selector bằng cách bấm chuột phải vào phần tử trong Chrome → Inspect → chuột phải node → Copy → Copy selector.

Các bước **chung** vẫn chạy nguyên vẹn trên web: Gõ chữ, Gửi phím, Chờ cố định, **Kiểm tra kết quả**, Ghi ra cột Excel. Lý do: bot dựng cây DOM thành đúng dạng XML mà phần đọc màn hình cũ vẫn đọc, nên toàn bộ luật so khớp từ khóa (bỏ dấu tiếng Việt), đọc câu trong hộp thoại và tự bấm nút đóng dùng lại y nguyên. Ở các bước chung, ô "Resource id" lúc này là `id` / `name` của thẻ HTML.

Ngược lại, các bước chỉ có ở Android — Chạm tọa độ, Chạm phần tử, Vuốt, Chụp màn hình qua ADB — không dùng trong kịch bản web. Đặt nhầm vào thì bước đó báo "chỉ chạy khi bot đang nối với trình duyệt" chứ không bị tính là lỗi thiết bị (tính nhầm là cả phiên tự dừng vì tưởng máy ảo chết).

### Giới hạn

- Một cửa sổ Chrome là một phiên đăng nhập, nên chế độ này chạy **một luồng**, không chia serial ra nhiều máy như LDPlayer.
- Bot chỉ **ngắt kết nối** khi chạy xong, không đóng Chrome của bạn.

## Trải nghiệm desktop

- **Nav rail** bên trái tách 2 trang: Chạy (điều khiển, thống kê, log) và Cấu hình — thay vì dồn hết vào một cửa sổ cuộn dài.
- **Menu bar** Tệp / Chạy / Công cụ / Trợ giúp, kèm phím tắt chuẩn: `Ctrl+O` mở Excel, `Ctrl+S` lưu profile, `Ctrl+Q` thoát.
- **Toolbar** Bắt đầu / Tạm dừng / Dừng luôn hiển thị ở mọi trang.
- **Status bar** hiện chấm màu tình trạng ADB, backend đang dùng và tiến độ.
- **Thu nhỏ xuống khay hệ thống**: khi bot đang chạy, nút X sẽ thu app xuống tray thay vì thoát. Biểu tượng tray **đổi màu theo trạng thái** (xám chờ, cyan chạy, vàng tạm dừng, đỏ lỗi), tooltip hiện tiến độ, chuột phải để Tạm dừng/Dừng/Thoát mà không cần mở cửa sổ.
- **Chặn mở 2 cửa sổ** — hai bản chạy song song sẽ gửi lệnh chồng nhau vào cùng một máy ảo LDPlayer.
- **Kéo thả file `.xlsx`** thẳng vào cửa sổ.
- **Nhớ vị trí và kích thước cửa sổ** giữa các lần mở.
- **Công cụ → Kiểm tra kết nối ADB** để thử từng instance trước khi chạy.

## Bộ icon

Icon được sinh bằng code, không lưu file nhị phân thiết kế trong repo:

```bash
python tools/make_icons.py
```

Sinh ra `assets/app.ico` (16, 24, 32, 48, 64, 256) và 4 biến thể tray. Các cỡ nhỏ (16, 24) được **vẽ riêng**, bỏ hẳn 3 dòng bảng tính và chỉ giữ dấu tick nét dày — thu nhỏ tự động từ bản 256 sẽ thành vệt mờ không đọc được ở taskbar.

## Sử dụng

### Chạy từng serial

1. **Chọn file Excel** (.xlsx) chứa danh sách serial — sheet và cột serial sẽ tự động được gợi ý.
2. Kiểm tra/chỉnh **cột serial**, **hàng bắt đầu/kết thúc**, **delay**. Nếu app đòi quét mã sản phẩm trước mỗi serial thì điền thêm ô **Mã sản phẩm cố định** — xem mục [Dán mã sản phẩm cố định trước mỗi serial](#dán-mã-sản-phẩm-cố-định-trước-mỗi-serial).
3. Bấm **Refresh** để nạp danh sách instance LDPlayer, tick một hoặc nhiều instance muốn chạy (để trống thì dùng ô "Fallback instance name").
4. Nhấn **Start** → xem trước danh sách trong hộp thoại Preview, bỏ chọn dòng không cần thiết nếu có → xác nhận.
5. Theo dõi **thống kê**, **log**, tiến độ từng instance (nếu chạy song song).
6. Khi xong, mở lại file Excel nguồn và xem sheet `Ket qua <timestamp>` bot vừa thêm; muốn báo cáo tổng hợp thành file riêng thì bấm **Export Report**.

> Ghi thẳng vào file nguồn nên **đóng file trong Excel trước khi bấm Start**. Đang mở thì bot báo ngay lúc khởi động và vẫn chạy, nhưng không ghi được kết quả.
>
> **File có ô công thức:** thư viện ghi Excel không giữ được *giá trị đã tính* của ô công thức — công thức còn nguyên nhưng ô rỗng cho tới khi bạn mở bằng Excel và lưu lại. Bot đọc file bằng `data_only=True`, nên nếu **cột serial là công thức** (VLOOKUP, ghép chuỗi…) thì lần chạy sau sẽ đọc ra rỗng và bỏ qua hết các dòng. Bot tự dò và hỏi trước khi chạy; gặp cảnh báo này thì nên dán-đè cột serial thành giá trị tĩnh (Paste Values). File `.xlsm` thì macro được giữ nguyên.

### Chạy theo mã OR

1. Đổi **Kiểu chạy** sang *"Theo mã OR (xuất kho)"* — khung *Xuất kho theo mã OR* hiện ra.
2. **Chọn file Excel** — **Cột mã OR**, **Cột MVĐ** và **Serial column** tự điền theo dòng tiêu đề; kiểm tra lại rồi chỉnh hàng bắt đầu/kết thúc.
3. Điền **Mã tote** (`T001`) và **Mã bin** (`PYTES`) cho đúng kho đang chạy. Hai ô này giữ nguyên suốt lượt chạy — muốn đổi thì dừng rồi chạy lại. Để trống **Mã bin** nếu muốn bot đi theo vị trí app chỉ.
4. Bấm **Refresh**, tick **đúng một** instance LDPlayer đang chạy (để trống thì dùng ô "Fallback instance name"). Tick nhiều thì bot chỉ lấy cái đầu tiên.
5. Mở sẵn màn hình **Lấy hàng** trên LDPlayer (hoặc để ở menu chính — bot tự bấm vào).
6. Nhấn **Start** → đọc kỹ **cảnh báo** trong hộp xem trước, bỏ tick mã chưa muốn chạy → xác nhận.
7. Theo dõi progress bar (`3 / 12 mã OR`) và thanh trạng thái (bước hiện tại trong phiên). Muốn dừng thì bấm **Dừng** — nhớ dọn phiên đang dở trên LDPlayer trước khi chạy lại.
8. Khi xong, bấm **Export Report** để lấy file có sheet **Ma OR**.

## Cấu trúc dự án

```
bot auto/
├── main.py                  # Entry point + chặn mở 2 instance
├── bot_gui.py                # Giao diện PyQt6 (nav rail, menu, tray)
├── bot_worker.py             # Logic automation chạy trong QThread
├── automation_backend.py     # Backend ADB / pyautogui + AdbClient
├── browser_backend.py        # Backend Chrome qua CDP: đọc DOM, bấm bằng DOM
├── screen_reader.py          # Đọc & truy vấn màn hình qua uiautomator
├── actions.py                # Định nghĩa các loại bước + validate
├── action_runner.py          # Engine chạy kịch bản, resolve biến
├── action_editor.py          # Giao diện soạn kịch bản
├── ui_inspector.py           # UI Inspector + Chọn tọa độ
├── recipes.py                # Load/save kịch bản JSON
├── recipes/                  # Kịch bản đã lưu (classic.json, web-mau.json...)
├── pick_runner.py            # Logic xuất kho theo mã OR (từng bước trong 1 phiên lấy hàng)
├── inbound_runner.py         # Logic nhập hàng theo mã check-in (kế thừa PickRunner)
├── pick_worker.py            # Thread chạy cả hai luồng theo phiên
├── excel_reader.py           # Đọc file Excel + gộp serial theo mã phiên (OR / check-in)
├── excel_writer.py           # Ghi kết quả + báo cáo Excel (có sheet theo phiên)
├── session_manager.py        # Checkpoint/resume phiên chạy
├── preview_dialog.py         # Hộp thoại xem trước & validate (serial / theo phiên)
├── logger_setup.py           # Cấu hình log ra file
├── version.py                # Tên app, phiên bản (dùng chung)
├── paths.py                  # Tách tài nguyên chỉ-đọc / dữ liệu ghi được
├── app_icons.py              # Nạp icon, hỗ trợ bundle PyInstaller
├── tools/make_icons.py       # Sinh bộ icon từ code
├── assets/                   # app.ico + icon tray (do script sinh)
├── tests/                    # Bộ test pytest
├── requirements.txt
├── requirements-dev.txt      # + pytest, pyinstaller
├── SerialPasteBot.spec       # Spec PyInstaller (onefile / onedir)
├── installer/                # Kịch bản Inno Setup sinh bộ cài .exe
├── build_installer.ps1       # Build payload + đóng gói bộ cài bằng 1 lệnh
├── version_info.txt          # Metadata nhúng vào EXE
└── README.md
```

## Chạy test

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## Đóng gói & cài đặt trên Windows

Có hai dạng phân phối, dùng chung một spec:

| Dạng | Lệnh build | Kết quả | Khi nào dùng |
|---|---|---|---|
| **Bộ cài** (khuyến nghị) | `powershell -ExecutionPolicy Bypass -File build_installer.ps1` | `dist/installer/SerialPasteBot-Setup-<ver>.exe` | Giao cho người dùng cuối: có lối tắt Start Menu/Desktop, gỡ cài đặt trong Apps & features, mở app nhanh |
| **Portable 1 file** | `python -m PyInstaller SerialPasteBot.spec --noconfirm` | `dist/SerialPasteBot.exe` (~57 MB) | Chép USB chạy tạm, không cài gì lên máy |

### Build bộ cài

```bash
pip install -r requirements-dev.txt
winget install JRSoftware.InnoSetup
powershell -ExecutionPolicy Bypass -File build_installer.ps1
```

Script tự đọc `APP_VERSION` trong `version.py`, build payload bằng PyInstaller ở chế độ **onedir** rồi gọi Inno Setup nén lại. Thêm `-Portable` nếu muốn ra luôn cả bản 1 file (vào `dist/portable/`).

> Bộ cài dùng onedir chứ không nhúng bản 1 file: bản 1 file phải giải nén ~60 MB ra `%TEMP%` **mỗi lần mở** (chậm vài giây), còn app đã cài thì không cần chịu chi phí đó. Đổi lại thư mục cài chiếm ~140 MB trên đĩa.

### Chuyển bot sang máy khác

Máy đích **không cần Python, không cần mã nguồn**. Chỉ cần một trong hai file build ra ở trên.

Chuẩn bị trên máy đích, theo thứ tự:

1. **LDPlayer** đã cài, và **app kho đã đăng nhập sẵn** trong máy ảo. Bot không tự đăng nhập.
2. Máy ảo **đang bật** và ADB nối được. Kiểm nhanh bằng `adb devices` — phải thấy một dòng `device`.
3. Nếu LDPlayer cài chỗ lạ: đặt `LDPLAYER_DIR` (xem mục [Bot tìm LDPlayer ở đâu](#bot-tìm-ldplayer-ở-đâu)).
4. Chép **file Excel** đơn hàng sang.
5. Mở app → bấm **Refresh** để lấy danh sách máy ảo → chọn đúng tên instance.
6. Kiểm lại khung **Cấu hình**: mã tote (`T001`) và mã bin (`PYTES`) là mặc định của kho hiện tại — kho khác thì phải sửa.

Các ô cấu hình được nhớ theo từng tài khoản Windows (QSettings), nên máy mới lần đầu chạy sẽ về mặc định — xem lại một lượt trước khi bấm Start.

> Chạy thử **một mã OR** trước khi chạy cả danh sách. Hộp xem trước cho tick chọn từng mã, dùng nó để chạy đúng một dòng và xác nhận app phản hồi đúng trên máy mới.

### Người dùng cài như thế nào

Chạy `SerialPasteBot-Setup-<ver>.exe` → Tiếp tục → Cài đặt. Mặc định **cài cho riêng tài khoản hiện tại** vào `%LOCALAPPDATA%\Programs\Serial Paste Bot`, **không cần quyền admin, không hiện UAC**; ai muốn cài cho mọi tài khoản thì đổi ở trang đầu của wizard (lúc đó mới cần admin). Gỡ trong **Settings → Apps → Serial Paste Bot**, bộ gỡ sẽ hỏi có xóa luôn dữ liệu cá nhân không.

Nếu app đang chạy lúc cài/gỡ, bộ cài phát hiện qua mutex và nhắc đóng trước — không ghi đè file đang bị khóa.

> Máy client **không bao giờ cần mã nguồn**. Lỗi `Python was not found` khi chạy `python main.py` nghĩa là ai đó đã chép nhầm thư mục source sang thay vì cài bằng bộ cài — bản đóng gói đã nhúng sẵn Python và PyQt trong `.exe`.

### Đẩy bản mới xuống máy client

Máy client mới tinh thì đưa [`deploy/HUONG-DAN-CAI-DAT.md`](deploy/HUONG-DAN-CAI-DAT.md) — hướng dẫn đầy đủ từ khâu chuẩn bị LDPlayer tới chạy thử mã đầu tiên. Người vận hành kho thì đưa thêm [`deploy/HUONG-DAN-NHAP-XUAT-SERIAL.md`](deploy/HUONG-DAN-NHAP-XUAT-SERIAL.md) — cài đặt rút gọn và cách chạy nhập hàng (check-in), xuất kho (OR), đọc kết quả, xử lý khi dừng giữa chừng. Máy đã có bot thì chỉ cần bản cập nhật.

Client giữ sẵn [`deploy/Cap-nhat.bat`](deploy/Cap-nhat.bat) trên Desktop. Ra bản mới thì họ bấm lại đúng file đó: script tải bộ cài mới nhất từ GitHub Releases, tự đóng app nếu đang mở, cài đè im lặng rồi mở lại app. Không cần Python, không cần quyền admin, không hiện UAC. Dữ liệu trong `%LOCALAPPDATA%\SerialBot` nằm ngoài thư mục cài nên không bị đụng tới.

Quy trình phát hành bốn bước nằm trong [`deploy/README.md`](deploy/README.md). Bước dễ quên nhất là lúc upload: phải **đổi tên file thành `SerialPasteBot-Setup.exe` trước khi kéo vào release**, bỏ số phiên bản (web GitHub không cho sửa tên asset sau khi upload), để link tải giữ nguyên qua mọi bản:

```
https://github.com/nguyenmanhquynh444-lang/serialbot/releases/latest/download/SerialPasteBot-Setup.exe
```

Đó là lý do `Cap-nhat.bat` chỉ phát cho client đúng một lần. Nhớ tăng `APP_VERSION` trong `version.py` **và** sửa cho khớp trong `version_info.txt` trước khi build, không thì về sau không truy được máy client đang chạy code ngày nào.

### Dữ liệu lưu ở đâu

Bản **đã cài** không ghi gì vào thư mục cài (Program Files là chỉ-đọc, và thư mục giải nén của bản 1 file bị xóa lúc thoát). Mọi thứ ghi ra nằm trong `%LOCALAPPDATA%\SerialBot\`:

```
%LOCALAPPDATA%\SerialBot\
├── logs/           # log từng phiên chạy (menu Công cụ → Mở thư mục log)
├── screenshots/    # ảnh chụp bằng chứng khi lỗi/unknown
├── recipes/        # kịch bản (kịch bản mặc định được chép sang lần chạy đầu)
├── device_profile.json  # những gì đã dò được về máy ảo + app, để phiên sau chạy nhanh ngay
├── run_journal.sqlite3  # ý định, kết quả và trạng thái phục hồi bền vững
└── session.json    # checkpoint cũ, chỉ dùng tham khảo
```

Chạy từ mã nguồn (`python main.py`) thì vẫn ghi cạnh dự án như trước — xem `paths.py`.

## Chạy nền (dùng máy làm việc khác)

Tick **Background mode** trong phần CONFIG. Khi bật:

- Ô "Use ADB input" bị khóa ở trạng thái bật (background mode chỉ chạy được qua ADB).
- Trước khi chạy, bot **kiểm tra ADB tới từng instance đã chọn**. Nếu instance nào không phản hồi, bot báo lỗi và **không chạy** — thay vì chạy rồi hỏng giữa chừng.
- Nếu ADB chết giữa chừng, serial đó được đánh dấu `UNKNOWN` (không phải `OK`), và sau 5 serial lỗi liên tiếp bot **tự tạm dừng** để bạn kiểm tra, thay vì đánh dấu sai hàng loạt dòng còn lại.
- Bot **không bao giờ** chuyển sang gõ bàn phím ở chế độ này.

LDPlayer có thể minimize hoặc bị che — lệnh ADB đi thẳng vào máy ảo Android, không qua bàn phím/chuột Windows.

> Khuyến nghị: bật kèm **Verify result via ADB**. Khi bạn dùng máy làm việc khác, CPU bị chia sẻ nên app trong LDPlayer phản hồi chậm hơn — không có verify thì bot không biết app đã xử lý xong hay chưa.

## Lưu ý quan trọng

- **ADB input/verify** cần LDPlayer cài tại đường dẫn mặc định (`C:\LDPlayer\LDPlayer9`, `LDPlayer64` hoặc `LDPlayer4.0`). Nếu không tìm thấy `adb.exe`/`ldconsole.exe`, bot tự chuyển sang gõ bàn phím — lúc đó cần **không di chuột/gõ phím** trong lúc chạy và tên cửa sổ LDPlayer phải khớp tiêu đề thật. **Trừ khi bật Background mode** thì bot dừng hẳn thay vì fallback.
- `pyautogui.FAILSAFE` đang bật ở chế độ fallback: kéo chuột vào góc trên-trái màn hình để dừng khẩn cấp.
- Kết quả `UNKNOWN` nghĩa là bot không xác nhận được qua ADB (mất kết nối, timeout...) — nên bật "Screenshot on error/unknown" để kiểm tra lại thủ công.
