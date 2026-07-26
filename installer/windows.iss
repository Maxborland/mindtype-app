; =============================================================================
; Inno Setup script for MindType
; Compile: ISCC.exe windows.iss
; With version: ISCC.exe /DAppVersion=1.1.0 windows.iss
; =============================================================================

#ifndef AppVersion
  #define AppVersion "0.9.3"
#endif

#ifndef AppName
  #define AppName "MindType"
#endif

#define AppPublisher "MindType"
#define AppURL "https://mindtype.space"
#define AppExeName "MindType.exe"
#define AppId "{{B2C3D4E5-F6A7-8901-BCDE-F12345678901}"

[Setup]
; Application info
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/updates

; Installation paths
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes

; Output settings
OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile=..\assets\icons\app.ico
UninstallDisplayIcon={app}\{#AppExeName}

; Compression (maximum)
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMADictionarySize=65536
LZMANumFastBytes=64

; Privileges
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Appearance
WizardStyle=modern
WizardSizePercent=120,120
WizardImageFile=..\assets\icons\wizard_large.bmp
WizardSmallImageFile=..\assets\icons\wizard_small.bmp
DisableWelcomePage=no
DisableDirPage=no

; Version info
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=MindType - Hybrid Voice-to-Text
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoCopyright=Copyright (c) 2024-2026 {#AppPublisher}

; Signing (uncomment and configure for production)
; SignTool=signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 /a $f

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "{cm:StartupTask}"; GroupDescription: "{cm:AdditionalOptions}"; Flags: unchecked

[Files]
; Main application files (from PyInstaller build)
Source: "..\dist\MindType\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start menu
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "Hybrid Voice-to-Text"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"

; Desktop icon (optional)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; Comment: "Hybrid Voice-to-Text"

[Registry]
; Autostart (optional)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: startupicon

; App registration
Root: HKCU; Subkey: "Software\{#AppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#AppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#AppVersion}"; Flags: uninsdeletekey

[Run]
; Launch after install
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Close app before uninstall
Filename: "taskkill"; Parameters: "/F /IM {#AppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
// Custom messages
const
  STARTUP_TASK = 'Run {#AppName} when Windows starts';
  ADDITIONAL_OPTIONS = 'Additional options:';

// Check if app is running
function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec('tasklist', '/FI "IMAGENAME eq {#AppExeName}" /NH /FO CSV', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := ResultCode = 0;
  end;
end;

// Close app before update/uninstall
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Retries: Integer;
begin
  Result := '';
  Retries := 0;

  // Try to close the app gracefully
  while IsAppRunning() and (Retries < 3) do
  begin
    Exec('taskkill', '/IM {#AppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1000);
    Retries := Retries + 1;
  end;

  // Force kill if still running
  if IsAppRunning() then
  begin
    Exec('taskkill', '/F /IM {#AppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);
  end;
end;

// Initialize setup
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

// System-7 вид: белый фон, чёрный текст, жирные заголовки (плоско, B&W).
// Только цвет/шрифт стандартных контролов — без риска для разметки визарда.
procedure InitializeWizard();
begin
  WizardForm.Color := clWhite;
  WizardForm.MainPanel.Color := clWhite;
  WizardForm.PageNameLabel.Font.Style := [fsBold];
  WizardForm.WelcomeLabel1.Font.Style := [fsBold];
  WizardForm.FinishedHeadingLabel.Font.Style := [fsBold];
end;

// Initialize uninstall
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // Close app before uninstall
  Exec('taskkill', '/F /IM {#AppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
end;

// Post-install actions
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Additional post-install actions can be added here
  end;
end;

[CustomMessages]
english.StartupTask=Run {#AppName} when Windows starts
english.AdditionalOptions=Additional options:
english.LaunchAfterInstall=Launch {#AppName} after installation

russian.StartupTask=Запускать {#AppName} при старте Windows
russian.AdditionalOptions=Дополнительные параметры:
russian.LaunchAfterInstall=Запустить {#AppName} после установки

german.StartupTask={#AppName} beim Windows-Start ausführen
german.AdditionalOptions=Zusätzliche Optionen:
german.LaunchAfterInstall={#AppName} nach der Installation starten

french.StartupTask=Lancer {#AppName} au démarrage de Windows
french.AdditionalOptions=Options supplémentaires:
french.LaunchAfterInstall=Lancer {#AppName} après l'installation

spanish.StartupTask=Ejecutar {#AppName} al iniciar Windows
spanish.AdditionalOptions=Opciones adicionales:
spanish.LaunchAfterInstall=Iniciar {#AppName} después de la instalación
