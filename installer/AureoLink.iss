#define MyAppName "AUREO LINK"
#define MyAppVersion "2.0.1"
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
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=AureoLink-Setup
SetupIconFile=..\pwa\icons\aureo-link.ico
UninstallDisplayIcon={app}\AureoLink.exe
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
VersionInfoDescription=AUREO LINK 安裝程式

[Languages]
Name: "chinesetraditional"; MessagesFile: "ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "捷徑選項："

[Files]
Source: "..\dist\AureoLink.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\QUICK_START.txt"; DestDir: "{app}"; DestName: "使用說明.txt"; Flags: ignoreversion
Source: "..\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\LICENSE-cloudflared.txt"; DestDir: "{app}\licenses\cloudflared"; Flags: ignoreversion
Source: "..\tools\cloudflared-release.json"; DestDir: "{app}\licenses\cloudflared"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\AUREO LINK\AUREO LINK"; Filename: "{app}\AureoLink.exe"; WorkingDir: "{app}"; IconFilename: "{app}\AureoLink.exe"
Name: "{autoprograms}\AUREO LINK\使用說明"; Filename: "{app}\使用說明.txt"
Name: "{autodesktop}\AUREO LINK"; Filename: "{app}\AureoLink.exe"; WorkingDir: "{app}"; IconFilename: "{app}\AureoLink.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AureoLink.exe"; Description: "立即啟動 AUREO LINK"; Flags: nowait postinstall skipifsilent
