; Inno Setup script - builds IndAS116LeaseApp-Setup.exe
; Per-user install (no administrator rights needed). Lease data in %LOCALAPPDATA%\IndAS116LeaseApp
; is never touched by install, upgrade or uninstall.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8E6C2F1A-3B9D-4C2E-9A57-116A5E1E0001}
AppName=Ind AS 116 Lease Accounting
AppVersion={#AppVersion}
AppVerName=Ind AS 116 Lease Accounting {#AppVersion}
AppPublisher=Finance and Accounts
DefaultDirName={localappdata}\Programs\IndAS116LeaseApp
DefaultGroupName=Ind AS 116 Lease Accounting
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\installer_output
OutputBaseFilename=IndAS116LeaseApp-Setup
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\IndAS116LeaseApp.exe
UninstallDisplayName=Ind AS 116 Lease Accounting
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\IndAS116LeaseApp\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\templates\*"; DestDir: "{app}\Excel_Templates"; Flags: recursesubdirs ignoreversion
Source: "..\sample_data\*"; DestDir: "{app}\Sample_Data"; Flags: recursesubdirs ignoreversion
Source: "..\docs\*.md"; DestDir: "{app}\Documents"; Flags: ignoreversion
Source: "..\docs\Accounting_Test_Results.xlsx"; DestDir: "{app}\Documents"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Ind AS 116 Lease Accounting"; Filename: "{app}\IndAS116LeaseApp.exe"
Name: "{autodesktop}\Ind AS 116 Lease Accounting"; Filename: "{app}\IndAS116LeaseApp.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\IndAS116LeaseApp.exe"; Description: "Start Ind AS 116 Lease Accounting now"; Flags: nowait postinstall skipifsilent
