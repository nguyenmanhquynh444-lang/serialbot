import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_save_and_load_session_roundtrip(tmp_path, monkeypatch):
    import session_manager

    session_dir = tmp_path / "SerialBot"
    monkeypatch.setattr(session_manager, "SESSION_DIR", str(session_dir))
    monkeypatch.setattr(session_manager, "SESSION_PATH", str(session_dir / "session.json"))

    excel_path = str(tmp_path / "list.xlsx")
    session_manager.save_session(excel_path, [2, 3, 5], done=3, success=2, error=1, unknown=0)

    loaded = session_manager.load_session(excel_path)
    assert loaded is not None
    assert loaded["done_rows"] == [2, 3, 5]
    assert loaded["done"] == 3
    assert loaded["success"] == 2


def test_load_session_returns_none_for_different_file(tmp_path, monkeypatch):
    import session_manager

    session_dir = tmp_path / "SerialBot"
    monkeypatch.setattr(session_manager, "SESSION_DIR", str(session_dir))
    monkeypatch.setattr(session_manager, "SESSION_PATH", str(session_dir / "session.json"))

    session_manager.save_session(str(tmp_path / "a.xlsx"), [1], done=1, success=1, error=0, unknown=0)
    assert session_manager.load_session(str(tmp_path / "b.xlsx")) is None


def test_clear_session_removes_file(tmp_path, monkeypatch):
    import session_manager

    session_dir = tmp_path / "SerialBot"
    monkeypatch.setattr(session_manager, "SESSION_DIR", str(session_dir))
    monkeypatch.setattr(session_manager, "SESSION_PATH", str(session_dir / "session.json"))

    excel_path = str(tmp_path / "list.xlsx")
    session_manager.save_session(excel_path, [1], done=1, success=1, error=0, unknown=0)
    session_manager.clear_session()
    assert session_manager.load_session(excel_path) is None
