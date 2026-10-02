; TestAssistant AI 安装包脚本(Inno Setup 6)
; 构建: ISCC.exe testassistant.iss  →  dist/TestAssistant-Setup.exe

#define AppName "TestAssistant AI"
#define AppVersion "1.0.0"
#define AppPublisher "TestAssistant"
#define AppExeName "TestAssistantApp.exe"

[Setup]
AppId={{8E5F3B7A-2C4D-4E89-9A1B-TESTASSISTANT1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\TestAssistant
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 数据在 ~/.testassistant,卸载默认保留用户数据
UninstallDisplayIcon={app}\TestAssistantApp.exe
OutputDir=dist
OutputBaseFilename=TestAssistant-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; LZMA2 压缩 700MB 产物,内存占用调高换速度
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
ArchitecturesInstallIn64BitMode=x64compatible
; 允许命令行/向导选择"仅为当前用户安装"(免管理员,装到 %LOCALAPPDATA%Programs)
PrivilegesRequiredOverridesAllowed=dialog commandline

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\testassistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} 控制台模式(带日志)"; Filename: "{app}\TestAssistant.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 结束可能残留的进程,保证卸载干净
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM TestAssistant.exe & taskkill /F /IM TestAssistantApp.exe"; Flags: runhidden; RunOnceId: "KillProc"
