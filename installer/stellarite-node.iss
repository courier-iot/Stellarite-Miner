; Stellarite Node: Windows installer (Inno Setup 6)
;
; Installs the Pulsarite and Nebulite full nodes with their own Python, so the
; computer needs nothing else. Build it with installer\build.ps1, which stages
; Python and the node code into build\stage and then runs this script.

#define AppName "Stellarite Node"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\build\stage"
#endif

[Setup]
AppId={{8C5D2E61-4F3B-4A7E-9C1D-5B7A2E9F3C40}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Stellarite
VersionInfoVersion={#AppVersion}
; Per-user by default (no admin prompt, installs to %LOCALAPPDATA%\Programs).
; "Install for all users" is offered and also adds the firewall rule.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\Stellarite Node
DefaultGroupName=Stellarite Node
DisableProgramGroupPage=yes
DisableWelcomePage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build
OutputBaseFilename=StellariteNode-Setup-{#AppVersion}
SetupIconFile=art\stellarite-node.ico
UninstallDisplayIcon={app}\stellarite-node.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=art\wizard-100.bmp,art\wizard-200.bmp
WizardSmallImageFile=art\small-100.bmp,art\small-200.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes

[Messages]
WelcomeLabel1=[ STELLARITE NODE ]
WelcomeLabel2=This sets up full nodes for Pulsarite (PLSR) and Nebulite (NBLT) on this computer, with Python built in.%n%nPhones running Stellarite Miner on the same Wi-Fi can mine through them, and anyone can watch the network's work on the web map.%n%nTeaching coins only: they have no monetary value.
FinishedHeadingLabel=[ NODE ONLINE ]
FinishedLabel=Stellarite Node is installed.%n%nOn your phone, open Stellarite Miner and tap [FIND NODE] on the RIG tab. The node window shows the exact NODE_URI too.%n%nThe chains are kept in your AppData folder (Stellarite Node), so updating or uninstalling never deletes them.
BeveledLabel= STELLARITE // PLSR · NBLT

[Tasks]
Name: "desktopicon"; Description: "Desktop shortcut (starts both nodes)"
Name: "startup"; Description: "Start both nodes when I sign in to Windows"; Flags: unchecked
Name: "firewall"; Description: "Let phones on private networks connect (Windows Firewall, ports 5000-5001)"; Check: IsAdminInstallMode

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "stellarite-shell.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "art\stellarite-node.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Start both nodes"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.py"" all"; WorkingDir: "{app}"; IconFilename: "{app}\stellarite-node.ico"
Name: "{group}\Pulsarite node"; Filename: "{app}\python\python.exe"; Parameters: """{app}\launcher.py"" pulsarite"; WorkingDir: "{app}"; IconFilename: "{app}\stellarite-node.ico"
Name: "{group}\Nebulite node"; Filename: "{app}\python\python.exe"; Parameters: """{app}\launcher.py"" nebulite"; WorkingDir: "{app}"; IconFilename: "{app}\stellarite-node.ico"
Name: "{group}\Command deck (wallet and miner)"; Filename: "{cmd}"; Parameters: "/k ""{app}\stellarite-shell.cmd"""; WorkingDir: "{app}"; IconFilename: "{app}\stellarite-node.ico"
Name: "{group}\Pulsarite web map"; Filename: "http://localhost:5000/map"
Name: "{group}\Nebulite web map"; Filename: "http://localhost:5001/map"
Name: "{group}\Uninstall Stellarite Node"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Stellarite Node"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.py"" all"; WorkingDir: "{app}"; IconFilename: "{app}\stellarite-node.ico"; Tasks: desktopicon
Name: "{userstartup}\Stellarite Node"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.py"" all"; WorkingDir: "{app}"; IconFilename: "{app}\stellarite-node.ico"; Tasks: startup

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Stellarite Node"""; Flags: runhidden; Tasks: firewall
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Stellarite Node"" dir=in action=allow protocol=TCP localport=5000-5001 profile=private"; Flags: runhidden; Tasks: firewall
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\launcher.py"" all"; WorkingDir: "{app}"; Description: "Start both nodes now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Stellarite Node"""; Flags: runhidden; RunOnceId: "DelFirewall"; Check: IsAdminInstallMode

[UninstallDelete]
; Python's caches. Chains in AppData, and anything else you created, are left alone.
Type: filesandordirs; Name: "{app}\node\__pycache__"
Type: filesandordirs; Name: "{app}\nebulite\__pycache__"
Type: filesandordirs; Name: "{app}\python"
Type: dirifempty; Name: "{app}"

[Code]
const
  // Neon Pulsar palette. Inno colours are $BBGGRR.
  COL_BG      = $000000;  // pure black
  COL_PANEL   = $0A050E;  // black with a crimson cast
  COL_CRIMSON = $3C14DC;  // #DC143C
  COL_AMBER   = $00B0FF;  // #FFB000
  COL_TEXT    = $DCDCDC;
  COL_DIM     = $969696;

procedure StopRunningNodes();
var
  ResultCode: Integer;
begin
  // Closes node windows started from this install, so files can be replaced.
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ''' + ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningNodes();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopRunningNodes();
  Result := True;
end;

procedure InitializeWizard();
begin
  WizardForm.Color := COL_BG;
  WizardForm.WelcomePage.Color := COL_BG;
  WizardForm.InnerPage.Color := COL_BG;
  WizardForm.FinishedPage.Color := COL_BG;
  WizardForm.MainPanel.Color := COL_PANEL;

  // Headings in crimson, the HUD look
  WizardForm.WelcomeLabel1.Font.Color := COL_CRIMSON;
  WizardForm.WelcomeLabel1.Font.Name := 'Consolas';
  WizardForm.FinishedHeadingLabel.Font.Color := COL_CRIMSON;
  WizardForm.FinishedHeadingLabel.Font.Name := 'Consolas';
  WizardForm.PageNameLabel.Font.Color := COL_CRIMSON;
  WizardForm.PageNameLabel.Font.Name := 'Consolas';
  WizardForm.PageDescriptionLabel.Font.Color := COL_AMBER;
  WizardForm.BeveledLabel.Font.Color := COL_CRIMSON;
  WizardForm.BeveledLabel.Font.Name := 'Consolas';

  // Body text
  WizardForm.WelcomeLabel2.Font.Color := COL_TEXT;
  WizardForm.FinishedLabel.Font.Color := COL_TEXT;
  WizardForm.SelectDirLabel.Font.Color := COL_TEXT;
  WizardForm.SelectDirBrowseLabel.Font.Color := COL_TEXT;
  WizardForm.DiskSpaceLabel.Font.Color := COL_DIM;
  WizardForm.SelectTasksLabel.Font.Color := COL_TEXT;
  WizardForm.ReadyLabel.Font.Color := COL_TEXT;
  WizardForm.StatusLabel.Font.Color := COL_AMBER;
  WizardForm.FilenameLabel.Font.Color := COL_DIM;

  // Inputs and lists
  WizardForm.DirEdit.Color := COL_PANEL;
  WizardForm.DirEdit.Font.Color := COL_AMBER;
  WizardForm.TasksList.Color := COL_BG;
  WizardForm.TasksList.Font.Color := COL_TEXT;
  WizardForm.ReadyMemo.Color := COL_PANEL;
  WizardForm.ReadyMemo.Font.Color := COL_TEXT;
  WizardForm.ReadyMemo.Font.Name := 'Consolas';
  WizardForm.RunList.Color := COL_BG;
  WizardForm.RunList.Font.Color := COL_TEXT;
end;
