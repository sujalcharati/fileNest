; Inno Setup script: turns build\dist\FileNest into build\installer\FileNestSetup.exe
; Build with packaging\build.ps1 (it passes AppVersion).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F0D3C52-8E41-4B8A-9D3E-F11E5EA7C0DE}
AppName=FileNest
AppVersion={#AppVersion}
AppVerName=FileNest {#AppVersion}
AppPublisher=FileNest
AppPublisherURL=https://github.com/sujalcharati/fileNest
AppSupportURL=https://github.com/sujalcharati/fileNest/issues
; Per-user install: no administrator rights / UAC prompt needed.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\FileNest
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\build\installer
OutputBaseFilename=FileNestSetup
SetupIconFile=..\build\FileNest.ico
UninstallDisplayIcon={app}\FileNest.exe
UninstallDisplayName=FileNest
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Tasks]
Name: "startup"; Description: "Start FileNest automatically when I sign in (recommended)"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "..\build\dist\FileNest\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FileNest"; Filename: "{app}\FileNest.exe"
Name: "{autodesktop}\FileNest"; Filename: "{app}\FileNest.exe"; Tasks: desktopicon

[Registry]
; Same value the app's own "Start with Windows" toggle uses, so both stay in sync.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FileNest"; ValueData: """{app}\FileNest.exe"" --background"; Tasks: startup
; Always remove the auto-start entry on uninstall (it may have been added from the tray menu).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "FileNest"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\FileNest.exe"; Description: "Open FileNest now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im FileNest.exe"; Flags: runhidden; RunOnceId: "StopFileNest"

[UninstallDelete]
; The search index and settings.
Type: filesandordirs; Name: "{localappdata}\FileNest"

[Code]
// Close a running FileNest before files are replaced (upgrades).
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/f /im FileNest.exe', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
