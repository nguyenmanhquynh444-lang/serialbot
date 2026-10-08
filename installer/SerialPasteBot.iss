; SerialPasteBot.iss - Kịch bản Inno Setup 6 sinh bộ cài Windows.
;
; Không compile file này trực tiếp: chạy build_installer.ps1 ở thư mục gốc,
; nó build payload bằng PyInstaller (chế độ onedir) rồi gọi ISCC với đúng
; phiên bản đọc từ version.py.

#define AppName "Serial Paste Bot"
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define AppPublisher "SerialBotOrg"
#define AppExeName "SerialPasteBot.exe"
#define PayloadDir "..\dist\SerialPasteBot"

[Setup]
; AppId định danh app qua các phiên bản - ĐỪNG đổi, đổi là bản mới không nhận
; ra bản cũ và sẽ cài chồng thành 2 mục trong Apps & features.
AppId={{8E4F2C71-3A6D-4B58-9C0E-7D1F5A2B6E93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Mặc định cài cho riêng người dùng hiện tại (không cần quyền admin, không hiện
; UAC). Ai muốn cài cho mọi tài khoản thì chọn ở trang đầu của wizard.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; App gọi ADB/LDPlayer 64-bit, không có lý do chạy trên Windows 32-bit.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; Khớp mutex tạo trong main.py -> bộ cài/gỡ phát hiện app đang chạy và nhắc
; đóng, thay vì ghi đè file đang bị khóa rồi hỏng nửa chừng.
AppMutex=SerialPasteBotSetupMutex
CloseApplications=yes
RestartApplications=no

OutputDir=..\dist\installer
OutputBaseFilename=SerialPasteBot-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo lối tắt ngoài Desktop"; GroupDescription: "Lối tắt:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\OPTIMIZATION_NOTES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Mở {#AppName} ngay"; Flags: nowait postinstall skipifsilent

[Messages]
; Inno 6 không kèm gói tiếng Việt, nên dịch tay các chuỗi người dùng nhìn thấy.
SetupAppTitle=Cài đặt
SetupWindowTitle=Cài đặt - %1
ButtonNext=&Tiếp tục
ButtonBack=&Quay lại
ButtonInstall=&Cài đặt
ButtonCancel=Hủy
ButtonFinish=&Hoàn tất
ButtonBrowse=&Chọn thư mục...
ButtonYes=&Có
ButtonNo=&Không
ExitSetupTitle=Thoát cài đặt
ExitSetupMessage=Cài đặt chưa xong. Thoát bây giờ thì app sẽ không được cài.%n%nThoát?
WelcomeLabel1=[name] - trình cài đặt
WelcomeLabel2=Sẽ cài [name/ver] vào máy này.%n%nNên đóng các ứng dụng khác trước khi tiếp tục.
ClickNext=Nhấn Tiếp tục để đi tiếp, hoặc Hủy để dừng.
WizardSelectDir=Chọn nơi cài
SelectDirDesc=Cài [name] vào thư mục nào?
SelectDirLabel3=Bộ cài sẽ đặt [name] vào thư mục dưới đây.
SelectDirBrowseLabel=Nhấn Tiếp tục để dùng thư mục này, hoặc Chọn thư mục để đổi.
DiskSpaceGBLabel=Cần ít nhất [gb] GB trống.
DiskSpaceMBLabel=Cần ít nhất [mb] MB trống.
WizardSelectTasks=Tùy chọn thêm
SelectTasksDesc=Bạn muốn làm thêm việc gì?
SelectTasksLabel2=Chọn việc bộ cài nên làm, rồi nhấn Tiếp tục.
WizardReady=Sẵn sàng cài
ReadyLabel1=Bộ cài đã đủ thông tin để cài [name] vào máy.
ReadyLabel2a=Nhấn Cài đặt để bắt đầu, hoặc Quay lại để xem/sửa lại lựa chọn.
ReadyLabel2b=Nhấn Cài đặt để bắt đầu.
WizardInstalling=Đang cài
InstallingLabel=Vui lòng đợi trong lúc [name] được cài vào máy.
FinishedHeadingLabel=Đã cài xong [name]
FinishedLabel=[name] đã được cài vào máy. Mở app bằng lối tắt vừa tạo.
ClickFinish=Nhấn Hoàn tất để đóng bộ cài.
StatusUninstalling=Đang gỡ %1...
ConfirmUninstall=Bạn có chắc muốn gỡ %1 và toàn bộ thành phần của nó?
UninstalledAll=Đã gỡ %1 khỏi máy.

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  // Log, ảnh chụp, kịch bản và phiên đang dở nằm ngoài thư mục cài nên gỡ app
  // không đụng tới. Hỏi rõ thay vì im lặng xóa hoặc im lặng để lại rác.
  //
  // Gỡ im lặng (/VERYSILENT, winget, script triển khai) thì GIỮ dữ liệu: lúc đó
  // MsgBox trả về nút mặc định là "Có", tức là sẽ xóa sạch kịch bản của người
  // dùng mà không ai kịp trả lời.
  if UninstallSilent then
    Exit;

  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\SerialBot');
    if DirExists(DataDir) then
      if MsgBox('Xóa luôn dữ liệu cá nhân (log, ảnh chụp, kịch bản đã lưu, phiên chạy dở) trong:'
                + #13#10 + #13#10 + DataDir + #13#10 + #13#10
                + 'Chọn Không nếu bạn định cài lại và muốn giữ kịch bản.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
