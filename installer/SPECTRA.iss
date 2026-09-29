; SPECTRA (WSA2) Windows 설치 프로그램 — Inno Setup 6
; 컴파일: iscc /DAppVersion=2.1 installer\SPECTRA.iss
;   → installer\out\SPECTRA-Setup-<버전>.exe 생성
; onedir 빌드(dist\SPECTRA\)를 Program Files\WAYAUDIO\SPECTRA 에 설치한다. [WIN_ONEDIR]

#ifndef AppVersion
  #define AppVersion "0.0"      ; CI 에서 /DAppVersion=... 로 주입(미지정 시 폴백)
#endif

#define AppName "SPECTRA"
#define AppPublisher "WAYAUDIO"
#define AppExeName "SPECTRA.exe"
#define AppURL "https://wayaudio.com"

[Setup]
; AppId 는 절대 바꾸지 말 것 — 업그레이드/제거가 이 GUID 로 같은 앱을 식별한다.
AppId={{7A9F3C2E-5B4D-4E1A-9C8F-2D6E1B3A4F50}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\{#AppPublisher}\{#AppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=out
OutputBaseFilename=SPECTRA-Setup-{#AppVersion}
SetupIconFile=..\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 64비트 전용 앱 → 64비트 모드로 Program Files(64) 에 설치
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; onedir 빌드 폴더 전체(SPECTRA.exe + _internal\)를 설치 폴더로 복사
Source: "..\dist\SPECTRA\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
