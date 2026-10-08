"""
excel_reader.py
Read serial values from an Excel (.xlsx) file with openpyxl.
"""
import os
import re
import unicodedata

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter


class ExcelReadError(Exception):
    """Raised when an Excel file cannot be read."""

    pass


def _to_ascii_serial(value: str) -> str:
    value = value.replace("\u0110", "D").replace("\u0111", "d")
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in value if 32 < ord(ch) < 127)


def clean_serial(val) -> str:
    if val is None:
        return ""

    if isinstance(val, float):
        if val.is_integer():
            val_str = str(int(val))
        else:
            val_str = f"{val:.0f}"
    elif isinstance(val, int):
        val_str = str(val)
    else:
        val_str = str(val)

    val_str = re.sub(
        r"[\r\n\t\s\x00-\x1f\x7f-\x9f\ufeff\xa0]",
        "",
        val_str,
    )
    val_str = _to_ascii_serial(val_str)

    if val_str.endswith(".0") and val_str[:-2].isdigit():
        val_str = val_str[:-2]

    return val_str


def read_serials(
    file_path: str,
    sheet_name: str | None,
    column: str,
    start_row: int,
    end_row: int | None = None,
) -> list[dict]:
    """
    Read serials from one Excel column.

    Args:
        file_path: Path to a .xlsx file.
        sheet_name: Sheet name. None or empty means the first sheet.
        column: Column letter, for example "H".
        start_row: First row to read, 1-based.
        end_row: Last row to read (inclusive), 1-based. None/0 means no limit.

    Returns:
        A list like [{"row": int, "value": str}, ...] with empty rows skipped.

    Raises:
        ExcelReadError: If the file, sheet, or column is invalid.
    """
    if not file_path or not os.path.isfile(file_path):
        raise ExcelReadError(f"File not found: {file_path}")

    try:
        wb = load_workbook(file_path, data_only=True, read_only=True)
    except Exception as e:
        raise ExcelReadError(f"Cannot open Excel file: {e}")

    try:
        if sheet_name:
            if sheet_name not in wb.sheetnames:
                raise ExcelReadError(
                    f"Sheet '{sheet_name}' not found. "
                    f"Available sheets: {', '.join(wb.sheetnames)}"
                )
            ws = wb[sheet_name]
        else:
            ws = wb[wb.sheetnames[0]]

        try:
            col_idx = column_index_from_string(column.strip().upper())
        except Exception:
            raise ExcelReadError(f"Invalid column: '{column}'")

        if start_row < 1:
            raise ExcelReadError("Start row must be >= 1")
        if end_row and end_row < start_row:
            raise ExcelReadError("End row must be >= start row")

        results = []
        empty_streak = 0
        max_empty = 50
        current_row = start_row

        for row_cells in ws.iter_rows(
            min_row=start_row,
            max_row=end_row or None,
            min_col=col_idx,
            max_col=col_idx,
            values_only=True,
        ):
            raw_val = row_cells[0] if row_cells else None
            val_str = clean_serial(raw_val)

            if not val_str:
                empty_streak += 1
                if not end_row and empty_streak >= max_empty:
                    break
            else:
                empty_streak = 0
                results.append({"row": current_row, "value": val_str})

            current_row += 1

        return results
    finally:
        wb.close()


def get_sheet_names(file_path: str) -> list[str]:
    """Return sheet names from an Excel file."""
    if not file_path or not os.path.isfile(file_path):
        raise ExcelReadError(f"File not found: {file_path}")
    try:
        wb = load_workbook(file_path, read_only=True)
        names = wb.sheetnames
        wb.close()
        return names
    except Exception as e:
        raise ExcelReadError(f"Cannot read sheet names: {e}")


def read_rows(
    file_path: str,
    sheet_name: str | None,
    column: str,
    start_row: int,
    end_row: int | None = None,
    max_columns: int = 26,
) -> list[dict]:
    """
    Like read_serials, but also returns the other cells on each row so recipes
    can reference them with {cell:B}.

    Returns [{"row": int, "value": str, "cells": {"A": ..., "B": ...}}, ...]
    """
    if not file_path or not os.path.isfile(file_path):
        raise ExcelReadError(f"File not found: {file_path}")

    try:
        wb = load_workbook(file_path, data_only=True, read_only=True)
    except Exception as e:
        raise ExcelReadError(f"Cannot open Excel file: {e}")

    try:
        if sheet_name:
            if sheet_name not in wb.sheetnames:
                raise ExcelReadError(
                    f"Sheet '{sheet_name}' not found. "
                    f"Available sheets: {', '.join(wb.sheetnames)}"
                )
            ws = wb[sheet_name]
        else:
            ws = wb[wb.sheetnames[0]]

        try:
            col_idx = column_index_from_string(column.strip().upper())
        except Exception:
            raise ExcelReadError(f"Invalid column: '{column}'")

        if start_row < 1:
            raise ExcelReadError("Start row must be >= 1")
        if end_row and end_row < start_row:
            raise ExcelReadError("End row must be >= start row")

        results = []
        empty_streak = 0
        current_row = start_row
        width = max(col_idx, max_columns)

        for row_cells in ws.iter_rows(
            min_row=start_row,
            max_row=end_row or None,
            min_col=1,
            max_col=width,
            values_only=True,
        ):
            raw_val = row_cells[col_idx - 1] if len(row_cells) >= col_idx else None
            val_str = clean_serial(raw_val)

            if not val_str:
                empty_streak += 1
                if not end_row and empty_streak >= 50:
                    break
            else:
                empty_streak = 0
                cells = {
                    get_column_letter(i + 1): ("" if v is None else v)
                    for i, v in enumerate(row_cells)
                }
                results.append({"row": current_row, "value": val_str, "cells": cells})

            current_row += 1

        return results
    finally:
        wb.close()


def read_bill_groups(
    file_path: str,
    sheet_name: str | None,
    bill_column: str,
    serial_column: str,
    start_row: int,
    end_row: int | None = None,
    ref_column: str = "",
    code_label: str = "mã vận đơn",
) -> tuple[list[dict], list[str]]:
    """
    Gộp serial theo mã phiên (mã OR khi xuất kho, mã check-in khi nhập hàng).

    `bill_column` là cột chứa **mã bot sẽ gõ vào ô tìm kiếm của app**, và mỗi
    giá trị khác nhau trong cột đó là một phiên. `ref_column` là cột tham chiếu
    đi kèm - với template xuất kho đó là mã vận đơn (MVĐ): bot không gõ nó vào
    đâu cả, chỉ mang theo để ghi vào file kết quả và báo cáo.

    Ô mã phiên có thể là ô gộp trải trên nhiều dòng serial. openpyxl chỉ trả giá
    trị ở dòng trên cùng, các dòng còn lại là None - nên phải kéo giá trị xuống,
    không thì mỗi phiên chỉ nhận được đúng một serial.

    Trả về (groups, warnings):
        groups   = [{"bill", "ref", "first_row",
                     "rows": [{"row", "value", "ref"}]}]
        warnings = những chỗ đáng ngờ, để hiện ở màn hình xem trước thay vì
                   lặng lẽ chạy tiếp
    """
    if not file_path or not os.path.isfile(file_path):
        raise ExcelReadError(f"File not found: {file_path}")

    try:
        wb = load_workbook(file_path, data_only=True, read_only=True)
    except Exception as e:
        raise ExcelReadError(f"Cannot open Excel file: {e}")

    try:
        if sheet_name:
            if sheet_name not in wb.sheetnames:
                raise ExcelReadError(
                    f"Sheet '{sheet_name}' not found. "
                    f"Available sheets: {', '.join(wb.sheetnames)}"
                )
            ws = wb[sheet_name]
        else:
            ws = wb[wb.sheetnames[0]]

        try:
            bill_idx = column_index_from_string(bill_column.strip().upper())
            serial_idx = column_index_from_string(serial_column.strip().upper())
        except Exception:
            raise ExcelReadError(
                f"Cột không hợp lệ: bill='{bill_column}', serial='{serial_column}'"
            )
        ref_idx = 0
        if ref_column.strip():
            try:
                ref_idx = column_index_from_string(ref_column.strip().upper())
            except Exception:
                raise ExcelReadError(f"Cột tham chiếu không hợp lệ: '{ref_column}'")
            if ref_idx == serial_idx:
                raise ExcelReadError(
                    "Cột tham chiếu (MVĐ) và cột serial phải khác nhau."
                )
            if ref_idx == bill_idx:
                # Trỏ cả hai vào một cột thì cột tham chiếu không thêm thông tin
                # gì, nhưng cũng không sai tới mức phải chặn - chỉ bỏ đi.
                ref_idx = 0
        if bill_idx == serial_idx:
            raise ExcelReadError(f"Cột {code_label} và cột serial phải khác nhau.")
        if start_row < 1:
            raise ExcelReadError("Start row must be >= 1")
        if end_row and end_row < start_row:
            raise ExcelReadError("End row must be >= start row")

        groups: list[dict] = []
        warnings: list[str] = []
        seen_bills: dict[str, int] = {}
        seen_serials: dict[str, int] = {}
        current_bill = ""
        current_ref = ""
        empty_streak = 0
        current_row = start_row
        width = max(bill_idx, serial_idx, ref_idx)

        for row_cells in ws.iter_rows(
            min_row=start_row, max_row=end_row or None,
            min_col=1, max_col=width, values_only=True,
        ):
            raw_bill = row_cells[bill_idx - 1] if len(row_cells) >= bill_idx else None
            raw_serial = row_cells[serial_idx - 1] if len(row_cells) >= serial_idx else None
            bill = clean_serial(raw_bill)
            serial = clean_serial(raw_serial)

            header_bill = re.sub(r"[^a-z0-9]", "", bill.lower())
            header_serial = re.sub(r"[^a-z0-9]", "", serial.lower())
            if header_bill in ("or", "maor", "checkin", "macheckin", "bill", "mavandon", "mvd") and \
                    header_serial in ("serial", "seri", "imei", "sn", "soseri"):
                warnings.append(f"Dòng {current_row}: bỏ dòng tiêu đề '{bill}' / '{serial}'.")
                current_bill = ""
                current_ref = ""
                current_row += 1
                continue

            if bill:
                current_bill = bill
            if ref_idx:
                raw_ref = row_cells[ref_idx - 1] if len(row_cells) >= ref_idx else None
                ref = clean_serial(raw_ref)
                if ref:
                    current_ref = ref

            if not serial:
                empty_streak += 1
                if not end_row and empty_streak >= 50:
                    break
                current_row += 1
                continue
            empty_streak = 0

            if not current_bill:
                warnings.append(
                    f"Dòng {current_row}: có serial '{serial}' nhưng phía trên "
                    f"chưa có {code_label} nào - đã bỏ qua."
                )
                current_row += 1
                continue

            if serial in seen_serials:
                warnings.append(
                    f"Dòng {current_row}: serial '{serial}' trùng với dòng "
                    f"{seen_serials[serial]}."
                )
            else:
                seen_serials[serial] = current_row

            if not groups or groups[-1]["bill"] != current_bill:
                if current_bill in seen_bills:
                    # Cùng một mã nhưng nằm rời thành hai cụm: rất dễ là file bị
                    # sắp xếp lẫn, mà chạy tiếp thì thành hai phiên pick riêng.
                    warnings.append(
                        f"Dòng {current_row}: {code_label} '{current_bill}' đã xuất "
                        f"hiện ở dòng {seen_bills[current_bill]} rồi lại tách ra "
                        f"cụm khác - kiểm tra lại thứ tự file."
                    )
                else:
                    seen_bills[current_bill] = current_row
                groups.append(
                    {
                        "bill": current_bill,
                        "ref": current_ref,
                        "first_row": current_row,
                        "rows": [],
                    }
                )
            elif ref_idx and current_ref and groups[-1]["ref"] != current_ref:
                # Một phiên mà hai mã vận đơn: bot vẫn chạy được (nó chỉ gõ mã
                # phiên), nhưng cột MVĐ ghi ra sẽ chỉ giữ được một giá trị - nói
                # trước còn hơn để người đọc báo cáo tưởng cả phiên là một đơn.
                warnings.append(
                    f"Dòng {current_row}: {code_label} '{current_bill}' có nhiều "
                    f"mã vận đơn ('{groups[-1]['ref']}' và '{current_ref}') - "
                    f"báo cáo chỉ ghi được mã đầu tiên."
                )

            row_entry = {"row": current_row, "value": serial}
            if ref_idx:
                row_entry["ref"] = current_ref
            groups[-1]["rows"].append(row_entry)
            current_row += 1

        # Trỏ nhầm "Cột mã vận đơn" vào một cột serial là kiểu sai không lộ ra ở
        # đâu cả: file đọc trơn tru, hộp xem trước hiện một đống vận đơn trông
        # như thật, tới lúc bot tìm phiên pick mới chết. Mã vận đơn mà cũng nằm
        # trong cột serial thì gần như chắc chắn là chọn nhầm cột.
        overlap = [b for b in seen_bills if b in seen_serials]
        if overlap:
            warnings.append(
                f"{len(overlap)} mã vận đơn cũng xuất hiện trong cột serial "
                f"(ví dụ '{overlap[0]}') - nhiều khả năng 'Cột mã vận đơn' đang "
                f"trỏ nhầm vào một cột chứa serial."
            )

        return groups, warnings
    finally:
        wb.close()


SERIAL_HEADER_KEYWORDS = ("serial", "seri", "imei")
# Tiêu đề đã bị bỏ dấu và bỏ khoảng trắng trước khi so, nên "Mã vận đơn" thành
# "mavandon", "MVĐ" thành "mvd" - từ khóa phải viết liền theo đúng dạng đó.
BILL_HEADER_KEYWORDS = ("vandon", "bill", "madon", "donhang", "waybill", "mvd")
# Cột mã OR thường chỉ đề đúng chữ "OR", mà "or" là khúc con của quá nhiều từ
# ("order", "form"...) nên chỉ nhận khi cả tiêu đề đúng bằng nó.
OR_HEADER_KEYWORDS = ("maor", "soor", "orcode", "ordercode")
OR_HEADER_EXACT = ("or", "ors", "maor")


def _guess_column_by_header(
    file_path: str,
    sheet_name: str | None,
    keywords,
    header_row: int,
    exact: tuple = (),
) -> str | None:
    if not file_path or not os.path.isfile(file_path):
        return None
    try:
        wb = load_workbook(file_path, read_only=True)
    except Exception:
        return None

    try:
        ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb[wb.sheetnames[0]]
        for row_cells in ws.iter_rows(min_row=header_row, max_row=header_row, values_only=False):
            for cell in row_cells:
                text = _to_ascii_serial(str(cell.value or "")).lower()
                if not text:
                    continue
                if text in exact or any(kw in text for kw in keywords):
                    return cell.column_letter
        return None
    except Exception:
        return None
    finally:
        wb.close()


def guess_serial_column(file_path: str, sheet_name: str | None, header_row: int = 1) -> str | None:
    """Scan a header row and return the column letter whose header text looks
    like a serial column (e.g. "Serial", "So Seri", "IMEI"). None if no match."""
    return _guess_column_by_header(file_path, sheet_name, SERIAL_HEADER_KEYWORDS, header_row)


def guess_bill_column(file_path: str, sheet_name: str | None, header_row: int = 1) -> str | None:
    """Như trên nhưng cho cột mã vận đơn ("Ma van don", "Mã vận đơn", "MVĐ")."""
    return _guess_column_by_header(file_path, sheet_name, BILL_HEADER_KEYWORDS, header_row)


def guess_or_column(file_path: str, sheet_name: str | None, header_row: int = 1) -> str | None:
    """Cột mã OR - mã bot gõ vào ô 'Tìm theo mã OR' của app khi xuất kho."""
    return _guess_column_by_header(
        file_path, sheet_name, OR_HEADER_KEYWORDS, header_row, exact=OR_HEADER_EXACT
    )
