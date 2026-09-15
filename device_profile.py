"""
device_profile.py
Nhớ qua từng phiên chạy những gì bot phải tự dò ra trên máy ảo.

Có sự thật về app chỉ trả lời được bằng cách CHỜ nó xảy ra: "hộp thoại lỗi của
app này có phải một cửa sổ riêng không" chỉ biết được khi có một hộp thoại lỗi
thật hiện ra. Phiên nào chạy sạch không lỗi thì không bao giờ trả lời được - và
đường nhanh dựa vào câu trả lời đó nằm im suốt phiên, mỗi dòng gánh thêm một lần
dump cả cây view (~1330ms) thay vì một câu hỏi cửa sổ (~130ms).

Đo trên log chạy thật: phiên 502 dòng ngày 21/08 không có dòng lỗi nào nên không
học được gì, nhịp 2.33s mỗi dòng; những phiên gặp lỗi sớm học được ngay từ đầu
chạy 1.74-1.79s. Cùng một app, cùng một máy ảo, chênh nhau nửa giây mỗi dòng chỉ
vì câu trả lời đó không sống qua nổi lúc đóng chương trình.

Khóa gồm cả versionCode của app: app cập nhật là mọi kết luận về cách nó vẽ hộp
thoại đều hết hiệu lực, lúc đó dò lại từ đầu còn hơn tin vào bản cũ. Không đọc
được versionCode thì không ghi và cũng không đọc - thà chậm còn hơn tin nhầm.
"""
import json
import logging
import os

from paths import user_data_dir

logger = logging.getLogger(__name__)

FILENAME = "device_profile.json"


def profile_path() -> str:
    return os.path.join(user_data_dir(), FILENAME)


def device_key(instance_name: str, package: str, version_code: str) -> str:
    """Khóa nhận dạng 'máy ảo + app + phiên bản app'. Thiếu phần nào thì bỏ."""
    if not (instance_name and package and version_code):
        return ""
    return f"{instance_name}|{package}|{version_code}"


def _read_all() -> dict:
    try:
        with open(profile_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load(key: str) -> dict:
    """Những gì đã dò được cho khóa này ở phiên trước. Không có thì trả {}."""
    if not key:
        return {}
    entry = _read_all().get(key)
    return entry if isinstance(entry, dict) else {}


def save(key: str, values: dict) -> None:
    """
    Ghi thêm/đè các khóa trong `values`, giữ nguyên phần còn lại.

    Hỏng file thì thôi, không làm đổ phiên chạy: đây chỉ là bộ nhớ để chạy nhanh
    hơn, mất nó thì bot dò lại từ đầu như trước chứ không sai kết quả.
    """
    if not key or not values:
        return

    data = _read_all()
    entry = data.get(key)
    if not isinstance(entry, dict):
        entry = {}
    entry.update(values)
    data[key] = entry

    path = profile_path()
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError as e:
        logger.warning("Không ghi được %s: %s", FILENAME, e)
