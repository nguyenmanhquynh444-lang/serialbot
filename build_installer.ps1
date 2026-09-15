# build_installer.ps1
# Build bộ cài Windows: PyInstaller (onedir) -> Inno Setup -> dist\installer\
#
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1 -Portable   # + bản 1 file
#
# Cần: pip install -r requirements-dev.txt  và  Inno Setup 6 (ISCC.exe).

param(
    [switch]$Portable,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# --- Phiên bản lấy từ version.py để .exe, bộ cài và tên file luôn khớp nhau ---
$versionLine = Select-String -Path "$root\version.py" -Pattern '^APP_VERSION\s*=\s*"([^"]+)"'
if (-not $versionLine) { throw "Không đọc được APP_VERSION trong version.py" }
$appVersion = $versionLine.Matches[0].Groups[1].Value
Write-Host "Serial Paste Bot $appVersion" -ForegroundColor Cyan

# --- Tìm ISCC.exe ---
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($candidate in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $candidate) { $iscc = $candidate; break }
    }
}
if (-not $iscc) {
    Write-Host ""
    Write-Host "Không tìm thấy Inno Setup 6 (ISCC.exe)." -ForegroundColor Yellow
    Write-Host "Cài bằng:  winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    Write-Host "hoặc tải ở https://jrsoftware.org/isdl.php rồi chạy lại script này."
    exit 1
}

if (-not $SkipBuild) {
    # --- Payload cho bộ cài: onedir, mở nhanh vì không phải giải nén ra %TEMP% ---
    Write-Host "[1/3] PyInstaller (onedir)..." -ForegroundColor Cyan
    Remove-Item "$root\dist\SerialPasteBot" -Recurse -Force -ErrorAction SilentlyContinue
    $env:SPB_BUILD = 'onedir'
    python -m PyInstaller SerialPasteBot.spec --noconfirm --distpath "$root\dist" --workpath "$root\build\onedir"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller thất bại (onedir)" }
    Remove-Item Env:\SPB_BUILD
} else {
    Write-Host "[1/3] Bỏ qua PyInstaller (-SkipBuild)" -ForegroundColor DarkGray
}

if (-not (Test-Path "$root\dist\SerialPasteBot\SerialPasteBot.exe")) {
    throw "Thiếu dist\SerialPasteBot\SerialPasteBot.exe - build payload trước khi đóng gói."
}

Write-Host "[2/3] Inno Setup..." -ForegroundColor Cyan
& $iscc "/DAppVersion=$appVersion" "$root\installer\SerialPasteBot.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC thất bại" }

if ($Portable) {
    Write-Host "[3/3] Bản portable 1 file..." -ForegroundColor Cyan
    $env:SPB_BUILD = 'onefile'
    python -m PyInstaller SerialPasteBot.spec --noconfirm --distpath "$root\dist\portable" --workpath "$root\build\onefile"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller thất bại (onefile)" }
    Remove-Item Env:\SPB_BUILD
} else {
    Write-Host "[3/3] Bỏ qua bản portable (thêm -Portable nếu cần)" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Xong:" -ForegroundColor Green
Get-ChildItem "$root\dist\installer\SerialPasteBot-Setup-$appVersion.exe" |
    ForEach-Object { "  {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB) }
if ($Portable) {
    Get-ChildItem "$root\dist\portable\SerialPasteBot.exe" |
        ForEach-Object { "  {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB) }
}
