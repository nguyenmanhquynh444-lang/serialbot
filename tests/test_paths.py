import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import paths


def test_user_data_dir_is_project_when_running_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.user_data_dir() == os.path.dirname(os.path.abspath(paths.__file__))


def test_frozen_writes_go_to_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert paths.user_data_dir() == os.path.join(str(tmp_path), "SerialBot")
    # Thư mục con phải được tạo sẵn, không để chỗ gọi tự makedirs.
    assert os.path.isdir(paths.logs_dir())
    assert os.path.isdir(paths.screenshots_dir())
    assert os.path.isdir(paths.recipes_dir())


def test_seed_copies_bundled_recipes_without_overwriting(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "recipes").mkdir(parents=True)
    (bundle / "recipes" / "classic.json").write_text('{"name": "goc"}', encoding="utf-8")
    (bundle / "recipes" / "extra.json").write_text('{"name": "extra"}', encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths, "resource_dir", lambda: str(bundle))

    edited = os.path.join(paths.recipes_dir(), "classic.json")
    with open(edited, "w", encoding="utf-8") as f:
        f.write('{"name": "da sua"}')

    paths.seed_bundled_recipes()

    assert json.load(open(edited, encoding="utf-8"))["name"] == "da sua"
    assert os.path.isfile(os.path.join(paths.recipes_dir(), "extra.json"))


def test_seed_is_a_no_op_when_source_and_target_match(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    paths.seed_bundled_recipes()  # không được xóa/ghi đè recipes/ của dự án
    assert os.path.isfile(
        os.path.join(os.path.dirname(os.path.abspath(paths.__file__)), "recipes", "classic.json")
    )
