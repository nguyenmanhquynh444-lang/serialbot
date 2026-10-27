"""Evidence attached to a result, independent of its compatibility status."""
from screen_reader import dialog_message, list_nodes, normalize_match_text

CONFIRMED = "confirmed"
INFERRED = "inferred"
UNVERIFIED = "unverified"
VERIFICATION_LABELS = {
    CONFIRMED: "Đã xác nhận",
    INFERRED: "Không phát hiện lỗi",
    UNVERIFIED: "Chưa xác minh",
}


def classify_session_dialog(xml: str, mode: str = "pick") -> str:
    """Only documented completion/placement dialogs authorize closing a session."""
    text = normalize_match_text(dialog_message(xml, max_len=2000))
    errors = ("khong tim", "khong ton tai", "khong thuoc", "loi", "error",
              "failed", "invalid", "not found", "not belong", "tu choi")
    if any(word in text for word in errors):
        return "error"
    complete = (("cong viec lay hang da ket thuc", "picking session is finishing",
                 "picking completed", "picking session completed") if mode == "pick" else
                ("receiving session is finishing", "receiving session completed",
                 "cong viec nhan hang da ket thuc", "phien nhan hang da ket thuc"))
    placement = "vi tri can dat san pham vua lay"
    if any(word in text for word in complete):
        return "complete"
    if mode == "pick" and placement in text:
        return "placement"

    # Khoanh vùng hộp thoại không đoán được khi cấu trúc dump lạ, và câu báo kết
    # thúc phiên chỉ có ở đúng hộp thoại đó (màn hình phía sau không bao giờ in
    # nó) - nên tìm lại trên toàn bộ chữ của màn hình. Chỉ dùng cho hai câu đặc
    # thù này; từ khoá lỗi thì không, vì chúng rất dễ trùng chữ của trang nền.
    screen = normalize_match_text(" ".join(
        f"{n['text']} {n['content_desc']}" for n in list_nodes(xml)
    ))
    if any(word in screen for word in complete):
        return "complete"
    if mode == "pick" and placement in screen:
        return "placement"
    return "unknown"
