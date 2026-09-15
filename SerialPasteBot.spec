# -*- mode: python ; coding: utf-8 -*-
# Bản portable 1 file:   pyinstaller SerialPasteBot.spec
# Payload cho bộ cài:    SPB_BUILD=onedir pyinstaller SerialPasteBot.spec
#
# Bộ cài dùng onedir vì bản one-file phải giải nén ~60 MB ra %TEMP% mỗi lần mở
# (chậm vài giây và tốn đĩa); app đã cài thì không cần chịu chi phí đó.
import os

from PyInstaller.utils.hooks import collect_all

ONEDIR = os.environ.get('SPB_BUILD', 'onefile').lower() == 'onedir'

# Chế độ chạy trên trình duyệt cần trọn gói playwright, không chỉ phần mã Python:
# thư viện này gọi một driver Node nằm ngay trong thư mục package, thiếu nó thì
# bản đóng gói vẫn import được nhưng connect_over_cdp() đổ ngay lần chạy đầu.
#
# KHÔNG cần tải trình duyệt của playwright (`playwright install`): bot gắn vào
# Chrome sẵn có trên máy, nên phần nặng nhất không phải mang theo.
_pw_datas, _pw_binaries, _pw_hidden = collect_all('playwright')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_pw_binaries,
    datas=[('assets', 'assets'), ('recipes', 'recipes')] + _pw_datas,
    hiddenimports=_pw_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_options = dict(
    name='SerialPasteBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app.ico',
    version='version_info.txt',
)

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_options)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='SerialPasteBot',
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        runtime_tmpdir=None,
        **exe_options,
    )
