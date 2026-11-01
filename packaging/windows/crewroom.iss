; Crewroom for Windows: a normal installed program, built by packaging/windows/build.py.
;
; Updating: every version uses the same AppId and the same folder, so a newer CrewroomSetup.exe replaces the
; installed Crewroom in place (one entry in Settings > Apps, one set of shortcuts). Never change the AppId.
; Installs for the current user only, so it needs no admin rights.

#ifndef AppVersion
  #error Build with packaging/windows/build.py (it passes AppVersion, Src and PyDir)
#endif

[Setup]
AppId={{4F423017-F6A7-466B-9C5F-F6E5A6C5891C}
AppName=Crewroom
AppVersion={#AppVersion}
AppVerName=Crewroom {#AppVersion}
AppPublisher=Ghaith Saad Jawad
AppPublisherURL=https://karthus3560.github.io/crewroom/
AppSupportURL=https://github.com/Karthus3560/crewroom
AppComments=Your AI team, together: Claude Code and Codex working as one team.
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Crewroom
DisableDirPage=yes
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=CrewroomSetup-{#AppVersion}
SetupIconFile={#Src}\web\assets\app-icon.ico
UninstallDisplayIcon={app}\web\assets\app-icon.ico
UninstallDisplayName=Crewroom
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
LicenseFile={#Src}\LICENSE

[Tasks]
Name: desktopicon; Description: "Put a Crewroom shortcut on the Desktop"

[InstallDelete]
; An update replaces the program files completely, so nothing from an older version is left behind.
Type: filesandordirs; Name: "{app}\teamchat"
Type: filesandordirs; Name: "{app}\web"
Type: filesandordirs; Name: "{app}\skill"
Type: filesandordirs; Name: "{app}\python"

[Files]
Source: "{#Src}\teamchat\*.py"; DestDir: "{app}\teamchat"; Flags: ignoreversion
Source: "{#Src}\web\*"; DestDir: "{app}\web"; Flags: ignoreversion recursesubdirs
Source: "{#Src}\skill\*"; DestDir: "{app}\skill"; Flags: ignoreversion recursesubdirs
Source: "{#Src}\team.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Src}\serve.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Src}\TeamChat.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Src}\install.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Src}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Src}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PyDir}\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{autoprograms}\Crewroom"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\TeamChat.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\web\assets\app-icon.ico"; Comment: "Your AI team, together"
Name: "{autodesktop}\Crewroom"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\TeamChat.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\web\assets\app-icon.ico"; Comment: "Your AI team, together"; Tasks: desktopicon

[Run]
; The "team" skill for Claude and Codex, pointing at this program, plus the record `team status` reads.
Filename: "{app}\python\python.exe"; Parameters: "-I ""{app}\install.py"" --from-setup"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; StatusMsg: "Setting up the team skill for Claude and Codex..."
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\TeamChat.pyw"""; WorkingDir: "{app}"; Description: "Open Crewroom"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: "-I ""{app}\install.py"" --uninstall --from-setup"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveTeamSkill"

[UninstallDelete]
; Python writes these caches while Crewroom runs; they are not in the file list above.
Type: filesandordirs; Name: "{app}\teamchat\__pycache__"
Type: filesandordirs; Name: "{app}\__pycache__"

[Messages]
FinishedLabel=Crewroom is installed. Open it from the Start menu or the Desktop.%n%nYour chats are kept in %USERPROFILE%\.crewroom, also when you update or uninstall.

[Code]
// Ask a running Crewroom to stop before its files are replaced or removed. Requests already running keep going.
procedure StopCrewroom();
var
  Http: Variant;
begin
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.SetTimeouts(1000, 1000, 2000, 2000);
    Http.Open('POST', 'http://127.0.0.1:47800/api/shutdown', False);
    Http.SetRequestHeader('Content-Type', 'application/json');
    Http.SetRequestHeader('Origin', 'http://127.0.0.1:47800');
    Http.Send('{}');
    Sleep(1500);
  except
    // Nothing was running.
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopCrewroom();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopCrewroom();
  Result := True;
end;
