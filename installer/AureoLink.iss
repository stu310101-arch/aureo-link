#define MyAppName "Amos電腦手機連結器"
#define MyAppVersion "2.0.2"
#define MyAppPublisher "stu310101-arch"
#define MyAppURL "https://github.com/stu310101-arch/aureo-link"

[Setup]
AppId={{9ABF5441-8F5B-4352-80DC-F3B87625F2E9}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases/latest
DefaultDirName={localappdata}\Programs\AureoLink
DefaultGroupName={#MyAppName}
UsePreviousGroup=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=AmosLink-Setup
SetupIconFile=..\pwa\icons\aureo-link.ico
UninstallDisplayIcon={app}\icons\AmosLink-v{#MyAppVersion}.ico
WizardStyle=modern
DisableWelcomePage=no
DisableProgramGroupPage=yes
InfoBeforeFile=installer-info.txt
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
SetupMutex=AureoLink.Setup
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription=Amos電腦手機連結器 安裝程式
VersionInfoProductName=Amos電腦手機連結器

[Languages]
Name: "chinesetraditional"; MessagesFile: "ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "捷徑選項："

[Files]
Source: "..\pwa\icons\aureo-link.ico"; DestDir: "{app}\icons"; DestName: "AmosLink-v{#MyAppVersion}.ico"; Flags: ignoreversion
Source: "..\dist\AureoLink.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\QUICK_START.txt"; DestDir: "{app}"; DestName: "使用說明.txt"; Flags: ignoreversion
Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\LICENSE-cloudflared.txt"; DestDir: "{app}\licenses\cloudflared"; Flags: ignoreversion
Source: "..\tools\cloudflared-release.json"; DestDir: "{app}\licenses\cloudflared"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Amos電腦手機連結器\Amos電腦手機連結器"; Filename: "{app}\AureoLink.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icons\AmosLink-v{#MyAppVersion}.ico"; IconIndex: 0
Name: "{autoprograms}\Amos電腦手機連結器\使用說明"; Filename: "{app}\使用說明.txt"
Name: "{autodesktop}\Amos電腦手機連結器"; Filename: "{app}\AureoLink.exe"; WorkingDir: "{app}"; IconFilename: "{app}\icons\AmosLink-v{#MyAppVersion}.ico"; IconIndex: 0; Tasks: desktopicon

[InstallDelete]
Type: files; Name: "{autodesktop}\AUREO LINK.lnk"
Type: files; Name: "{autoprograms}\AUREO LINK\AUREO LINK.lnk"
Type: files; Name: "{autoprograms}\AUREO LINK\使用說明.lnk"

[Run]
Filename: "{app}\AureoLink.exe"; Description: "立即啟動 Amos電腦手機連結器"; Flags: nowait postinstall skipifsilent
