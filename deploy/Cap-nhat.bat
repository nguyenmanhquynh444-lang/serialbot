@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Cập nhật Serial Paste Bot

REM ===========================================================================
REM  Cap-nhat.bat - đưa máy client lên bản Serial Paste Bot mới nhất.
REM
REM  Giao cho client đúng 1 file này. Double-click là xong: tải bộ cài mới nhất,
REM  cài đè im lặng, mở lại app. Không cần Python, không cần quyền admin.
REM
REM  ------------------------------------------------------------------------
REM  Link dưới đây CỐ ĐỊNH qua mọi phiên bản, nhờ /releases/latest/ - GitHub tự
REM  trỏ về release mới nhất. Nhờ vậy file .bat này chỉ phát cho client đúng
REM  một lần, các bản sau họ bấm lại chính file cũ.
REM
REM  Đổi lại, mỗi lần phát hành PHẢI upload asset lên GitHub Releases với tên
REM  "SerialPasteBot-Setup.exe" - bỏ hẳn số phiên bản trong tên file. Đặt tên
REM  kèm số (SerialPasteBot-Setup-2.1.0.exe) là link dưới đây gãy ngay.
REM  Quy trình đầy đủ: deploy\README.md
REM  ------------------------------------------------------------------------

set "URL=https://github.com/nguyenmanhquynh444-lang/serialbot/releases/latest/download/SerialPasteBot-Setup.exe"

REM AppId trong installer\SerialPasteBot.iss + hậu tố _is1 của Inno Setup.
REM Dùng để đọc lại nơi đã cài và số phiên bản sau khi cài xong.
set "APPID={8E4F2C71-3A6D-4B58-9C0E-7D1F5A2B6E93}_is1"
set "TMPEXE=%TEMP%\SerialPasteBot-Setup.exe"

echo.
echo   Đang tải bản mới nhất... (khoảng 40 MB)
echo.

del "%TMPEXE%" >nul 2>&1

REM URL và TMPEXE truyền qua biến môi trường để khỏi vướng dấu nháy lồng nhau.
REM ProgressPreference tắt thanh tiến trình - riêng nó đã nhanh gấp nhiều lần.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "try { Invoke-WebRequest -Uri $env:URL -OutFile $env:TMPEXE -UseBasicParsing }" ^
  "catch { Write-Host ('   ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 goto :loiTai

REM Link hỏng thường trả về trang HTML báo lỗi chứ không phải file lỗi, nên
REM kiểm tra dung lượng: bộ cài thật ~40 MB, trang lỗi chỉ vài KB.
if not exist "%TMPEXE%" goto :loiTai
for %%F in ("%TMPEXE%") do if %%~zF LSS 1000000 goto :loiTai

echo   Đang cài đặt...
echo   (nếu app đang mở, bộ cài sẽ tự đóng app rồi cài đè)
echo.

start /wait "" "%TMPEXE%" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES
set "RC=%ERRORLEVEL%"
del "%TMPEXE%" >nul 2>&1
if not "%RC%"=="0" goto :loiCai

REM Cài im lặng thì bộ cài không tự mở app (cờ skipifsilent trong file .iss),
REM nên tự đọc nơi cài trong registry rồi mở giúp client.
set "APPDIR="
set "VER="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APPID%" /v InstallLocation 2^>nul ^| find "InstallLocation"') do set "APPDIR=%%B"
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APPID%" /v DisplayVersion 2^>nul ^| find "DisplayVersion"') do set "VER=%%B"
if not defined APPDIR for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APPID%" /v InstallLocation 2^>nul ^| find "InstallLocation"') do set "APPDIR=%%B"
if not defined VER for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\%APPID%" /v DisplayVersion 2^>nul ^| find "DisplayVersion"') do set "VER=%%B"

if defined VER (echo   Xong. Đã cài bản %VER%.) else (echo   Xong.)
echo.

if defined APPDIR if exist "%APPDIR%\SerialPasteBot.exe" (
    echo   Đang mở app...
    start "" "%APPDIR%\SerialPasteBot.exe"
    timeout /t 3 >nul
    exit /b 0
)

echo   Mở app bằng lối tắt Serial Paste Bot ngoài Desktop hoặc trong Start Menu.
echo.
pause
exit /b 0

:loiTai
echo.
echo   [LOI] Không tải được bộ cài.
echo.
echo   Thử lần lượt:
echo     1. Kiểm tra máy có vào mạng được không.
echo     2. Mở link này bằng trình duyệt xem có tải về được không:
echo        %URL%
echo     3. Nếu trình duyệt tải được mà file này thì không, nhiều khả năng
echo        do phần mềm diệt virus hoặc proxy công ty chặn - báo lại người
echo        phát hành để nhận bộ cài qua đường khác.
echo.
del "%TMPEXE%" >nul 2>&1
pause
exit /b 1

:loiCai
echo.
if "%RC%"=="2" (
    echo   [LOI] Quá trình cài bị hủy.
) else if "%RC%"=="5" (
    echo   [LOI] Quá trình cài bị hủy.
) else (
    echo   [LOI] Bộ cài chạy lỗi ^(mã %RC%^).
    echo.
    echo   Hay gặp nhất là app vẫn đang chạy và không đóng được. Hãy đóng
    echo   Serial Paste Bot ^(kể cả biểu tượng dưới khay hệ thống^) rồi chạy
    echo   lại file này. Vẫn lỗi thì gửi mã %RC% cho người phát hành.
)
echo.
pause
exit /b %RC%
