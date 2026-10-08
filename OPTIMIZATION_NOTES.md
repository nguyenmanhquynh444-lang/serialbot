# Triển khai tối ưu và phục hồi LDPlayer

Ngày 08/10/2026. Thay đổi áp dụng cho mã nguồn; chưa build installer hoặc chạy giao dịch kho thật.

## Tính đúng và dừng

- OR/check-in chỉ nhận serial khi bộ đếm tăng đúng một và tổng giữ nguyên, hoặc có hộp thoại hoàn tất đã biết ở đúng serial cuối. Lỗi và hộp thoại chưa biết dừng phiên. Danh sách serial đã xác nhận được giữ riêng với trạng thái đóng phiên.
- Vòng chờ kiểm tra Stop và deadline trước lần đọc/thao tác tiếp theo. Thời gian gọi ADB nằm trong deadline; ảnh bằng chứng có ngân sách riêng tối đa 1,5 giây. XML rỗng được đọc lại tối đa hai lần trong cùng deadline.
- Lệnh nhập thất bại hoặc mất phản hồi không được gửi lại qua transport khác. Với quét OR/check-in, bot đọc bộ đếm để đối chiếu; nếu không có bằng chứng thì dừng. Với từng serial, kết quả mơ hồ giữ UNKNOWN và ý định đang chờ đối chiếu.
- Cú pháp gộp phím được dò bằng lệnh trợ giúp trước thao tác nghiệp vụ. Lệnh gộp Enter chưa được xác minh không tự bấm thêm Enter nếu ô vẫn còn chữ.
- Stop giữ giao diện ở trạng thái đang dừng cho đến khi QThread thoát và Excel lưu xong hoặc báo thất bại. Stop cũng hủy đếm ngược; cấu hình và trình sửa recipe bị khóa trong lượt chạy. Không đóng ứng dụng trong khi worker còn hoạt động.
- Thời gian thoát còn phụ thuộc lệnh ADB đang chạy (timeout mặc định 8 giây), kiểm tra kết nối ban đầu và tác vụ lưu Excel. Khi Excel chưa thoát, bot tiếp tục khóa Start; không cưỡng bức hủy workbook giữa lúc ghi.

## Nhật ký và Excel

`run_journal.sqlite3` là nguồn phục hồi, nằm trong thư mục dữ liệu của bot (`paths.user_data_dir()`), cùng khu vực lưu profile/log. SQLite dùng WAL, synchronous FULL và khóa truy cập trong tiến trình.

Ý định được ghi trước thao tác, kết quả ghi ngay sau xử lý, phiên hoàn tất ghi sau khi xác minh đóng xong. Crash giữa hai mốc để lại thao tác đang chờ đối chiếu. Không xóa nhật ký khi Stop hoặc lưu Excel lỗi.

Resume khớp đường dẫn, sheet, mode, dòng được chọn, dữ liệu serial/mã phiên, recipe, cấu hình và instance. Bot thêm sheet kết quả không làm thay đổi nhận diện. Checkpoint JSON cũ chỉ được thông báo tham khảo.

Nếu có thao tác chưa rõ kết quả, kiểm tra và xử lý phiên trên app trước. Khi chọn tiếp tục đúng lượt cũ, bot bỏ phần đang dở, giữ mức chưa xác minh và chạy phần chưa làm. Nếu đổi dữ liệu/cấu hình, dùng **Đối chiếu tiến độ** trước khi chạy lượt mới; việc chấp nhận chạy lại là quyết định thủ công, không phải bot tự xác nhận giao dịch cũ.

Một QThread sở hữu workbook. Kết quả được cập nhật theo dòng nguồn, lưu mỗi 50 kết quả hoặc 30 giây, và khi kết thúc. Lưu qua file tạm cùng thư mục rồi thay thế file đích. File bị khóa: nhật ký vẫn giữ kết quả, giao diện báo **Chưa lưu Excel**, có nút **Lưu lại Excel** sau khi lượt chạy đã thoát. Resume phát lại kết quả đã lưu nhật ký vào cùng sheet kết quả, không thêm trùng dòng.

Export Report chạy trên QThread riêng với bản sao kết quả tại lúc bấm xuất, không chặn giao diện. File báo cáo phải khác file nguồn. Start và đóng ứng dụng chờ cả tác vụ xuất báo cáo kết thúc.

## Mức xác nhận

Trường `status` giữ OK/ERROR/UNKNOWN để tương thích. Trường `verification` bổ sung:

| Giá trị | Ý nghĩa |
|---|---|
| confirmed | Có bằng chứng được bộ xác nhận hỗ trợ |
| inferred | Đường nhanh không phát hiện lỗi; chưa có bằng chứng nhận hàng chắc chắn |
| unverified | Kết quả mơ hồ hoặc dữ liệu lịch sử không có mức xác nhận |

UI và báo cáo tách **Đã xác nhận** với **Không phát hiện lỗi**. Kết thúc và trước Pause có lượt kiểm tra phản hồi muộn; không thấy hộp thoại trong thời gian chờ vẫn chỉ là inferred. Phản hồi muộn sau Pause có thể sửa kết quả đã công bố trên đúng dòng cũ.

## Tối ưu đã bật và đo bằng mô phỏng

- Parse XML một lần mỗi snapshot qua cache giới hạn; các lần tra node không parse lại XML.
- Chỉ bỏ xóa khi snapshot chưa có thao tác xen giữa xác nhận đúng ô nhập trống. Ô tìm OR còn mã cũ vẫn xóa.
- Dùng lại màn hình quét/kết thúc/search, gồm check-in; không bật compressed hoặc ghép sleep trước dump.
- OR chuyển bin trước serial tiếp theo khi app yêu cầu. Tìm kiếm phân biệt đang tải, kết quả cũ, kết quả ổn định và kết quả rỗng có bằng chứng mới. Danh sách rỗng còn từ truy vấn cũ dẫn tới dừng chưa xác định.
- Profile được khóa khi đọc/ghi giữa các thread và tiến trình, file tạm có tên riêng. Preview chặn cặp tiêu đề MaOR/Serial.

So sánh runner trước sửa (Git HEAD lúc triển khai) và runner hiện tại bằng thiết bị giả, có hai thẻ OR ban đầu:

| Serial/phiên | Lệnh ADB trước → sau | Dump trước → sau | Chuỗi xóa ô trước → sau |
|---:|---:|---:|---:|
| 1 | 17 → 17 | 9 → 9 | 4 → 1 |
| 3 | 21 → 21 | 11 → 11 | 6 → 1 |
| 10 | 35 → 35 | 18 → 18 | 13 → 1 |

Đây là số thao tác trong mô phỏng, không phải tốc độ LDPlayer. Mẫu này giảm chặng xóa bên trong lệnh gộp; số lần gọi và dump giữ nguyên. Tìm kiếm chỉ có một thẻ chưa có bằng chứng thay đổi cần thêm một snapshot ổn định. Không có cơ sở từ các số trên để tuyên bố đạt giảm 5–15% serial hoặc 10–20% OR.

Lặp lại phép đếm (chọn revision trước sửa sau khi đã commit):

```powershell
python tools/benchmark_operations.py --baseline-ref HEAD
```

## Đo thực tế và phát hành

Kiểm thử tại máy phát triển: **430 test pass** trong 78,43 giây. Sau khi bổ sung chỉ mục resource-id và cache cây XML, **96 test hồi quy liên quan pass** trong 37,49 giây. Compile và `git diff --check` đạt. Bộ test toàn dự án còn một cảnh báo `ZipFile.__del__` khi dọn tài nguyên Excel (`ValueError: I/O operation on closed file`); không có test thất bại. Cảnh báo này cần theo dõi riêng, không được xem là bằng chứng đã kiểm chứng lưu Excel trên mọi workbook thực tế.

Log `PERF` chứa run_id, phiên bản kèm hash mã, mode, instance, thời gian xử lý cả lỗi, số dump và chi phí dump/focus/screenshot/input; tác vụ lưu Excel có bản ghi riêng. Thời gian Pause được ghi và trừ khỏi thời gian xử lý; cấu hình nằm trong log bắt đầu lượt chạy và metadata SQLite.

```powershell
python tools/analyze_performance.py logs
python -m pytest -q
```

Công cụ phân tích báo mean, median, P95, throughput và số lỗi theo từng run/version/mode. Throughput từ thời gian xử lý từng mục là tốc độ phục vụ, không phải tổng throughput đồng hồ khi nhiều instance chạy đồng thời. Đo thời gian gián đoạn và thao tác người dùng riêng.

Trước phát hành, thử trên môi trường kho thử nghiệm với các tập tương đương được duyệt: cùng máy/cấu hình, cùng phân bố số serial mỗi phiên, cả OR/check-in nhiều bin, tìm kiếm chậm, hộp thoại cuối, Stop và Excel bị khóa. Không chạy lại giao dịch kho thật chỉ để benchmark. Mục tiêu giảm thời gian vẫn là 5–15% serial, 10–20% OR; check-in cần baseline thực tế riêng.

Màn hình trung gian/check-in và hộp thoại chưa có fixture vẫn dừng để lưu bằng chứng. Chrome giữ phạm vi cũ; chưa triển khai xác minh đầy đủ sau mọi thao tác DOM. Chưa thực hiện kiểm thử đầu cuối trên LDPlayer thật, vì môi trường hiện tại chưa cung cấp tập giao dịch thử nghiệm được duyệt.
