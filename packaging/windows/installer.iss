; Inno Setup script for FolioOrb (per-user Windows installer).
;
; Compile in CI after PyInstaller has produced dist\FolioOrb\:
;   iscc /DMyAppVersion=4.3.0 /DMyOutputName=FolioOrb-Windows-x64-v4.3.0-Setup packaging\windows\installer.iss
;
; MyAppVersion is always the numeric app version (used for the file's version
; metadata, which must be numeric). MyOutputName is the full installer filename
; token, which for rolling main builds is main-<sha> and would be invalid as a
; version — so the two are kept separate.
;
; Per-user install (no admin / no UAC prompt), clean uninstall registered in
; Apps & Features, and a WebView2 runtime check so pywebview has a renderer on
; older Windows 10 machines (Windows 11 already ships it).

#define MyAppName "FolioOrb"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyOutputName
  #define MyOutputName "FolioOrb-Windows-x64-Setup"
#endif
#define MyAppPublisher "Umang Dhawan"
#define MyAppURL "https://github.com/udhawan97/FolioOrb"
#define MyAppExeName "FolioOrb.exe"

[Setup]
AppId={{7C4B2E9A-3D5F-4A21-9E6C-1F0A8B7D2C34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\FolioOrb
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename={#MyOutputName}
SetupIconFile=..\icons\FolioOrb.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; In-app updates run this installer silently over a running copy. Close the
; app if any file is in use (no prompt in silent mode); we relaunch it
; ourselves via the skipifnotsilent [Run] entry rather than the Restart Manager.
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\FolioOrb\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
; Silent in-app update: relaunch the freshly installed app automatically.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[Code]
function WebView2Installed: Boolean;
var
  pv: String;
begin
  Result := False;
  { The Evergreen WebView2 Runtime records its version under this client GUID. }
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) then
    if (pv <> '') and (pv <> '0.0.0.0') then
      Result := True;
  if not Result then
    if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', pv) then
      if (pv <> '') and (pv <> '0.0.0.0') then
        Result := True;
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  TmpFile: String;
  ResultCode: Integer;
begin
  if (CurStep = ssInstall) and (not WebView2Installed) then
  begin
    try
      TmpFile := ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe');
      { Official Microsoft-hosted Evergreen Bootstrapper (~2 MB). }
      if DownloadTemporaryFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703', 'MicrosoftEdgeWebview2Setup.exe', '', @OnDownloadProgress) > 0 then
        Exec(TmpFile, '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    except
      { Non-fatal: the app still installs. Most machines already have WebView2;
        anyone missing it can install it from Microsoft and relaunch. }
    end;
  end;
end;
