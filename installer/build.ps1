# Builds build\StellariteNode-Setup-<version>.exe
#
# Run from the repo root on Windows (PowerShell 5+):
#     powershell -ExecutionPolicy Bypass -File installer\build.ps1
# Needs: internet access, Python 3.12 on PATH (only to run pip at build time),
# and Inno Setup 6 (preinstalled on GitHub's windows-latest runners; otherwise
# `winget install JRSoftware.InnoSetup`).
param(
    [string]$Version = "",
    [string]$PythonVersion = "3.12.8"
)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Build = Join-Path $Root "build"
$Stage = Join-Path $Build "stage"

# Version: argument, else the first "## X.Y.Z" heading in CHANGELOG.md
if (-not $Version) {
    $m = Select-String -Path (Join-Path $Root "CHANGELOG.md") -Pattern '^## (\d+\.\d+\.\d+)' | Select-Object -First 1
    $Version = if ($m) { $m.Matches[0].Groups[1].Value } else { "0.0.0" }
}
Write-Host "Stellarite Node $Version" -ForegroundColor Red

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# 1. Embedded Python (python.org's embeddable zip: no installer, no registry)
$Py = Join-Path $Stage "python"
$Zip = Join-Path $Build "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $Zip)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $Zip
}
Expand-Archive $Zip -DestinationPath $Py

# The ._pth file fixes sys.path for the embedded build; add site-packages and site.
$Tag = ($PythonVersion -split '\.')[0..1] -join ''
$Pth = Join-Path $Py "python$Tag._pth"
@("python$Tag.zip", ".", "Lib\site-packages", "import site") | Set-Content -Path $Pth -Encoding ascii

# 2. Both nodes' dependencies, installed as Windows wheels for this exact Python
$Site = Join-Path $Py "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $Site | Out-Null
$Reqs = @("node\requirements.txt", "nebulite\requirements.txt") | ForEach-Object { Join-Path $Root $_ }
$pipArgs = @("-m", "pip", "install", "--no-cache-dir", "--only-binary=:all:",
             "--platform", "win_amd64", "--python-version", $PythonVersion,
             "--implementation", "cp", "--target", $Site)
foreach ($r in $Reqs) { $pipArgs += @("-r", $r) }
& python @pipArgs
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 3. Node source, without chains, caches or tests
$Skip = @("data", "data2", "__pycache__", "tests", ".pytest_cache")
foreach ($coin in @("node", "nebulite")) {
    $dest = Join-Path $Stage $coin
    robocopy (Join-Path $Root $coin) $dest /E /XD $Skip /XF "*.pyc" "wallet*.json" /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "copying $coin failed" }
}
$global:LASTEXITCODE = 0

# 4. Smoke test: the bundled Python must import every dependency
$PyExe = Join-Path $Py "python.exe"
& $PyExe -c "import importlib.metadata as m; print('bundled packages:', len(list(m.distributions())))"
if ($LASTEXITCODE -ne 0) { throw "bundled Python failed to start" }
foreach ($coin in @("node", "nebulite")) {
    # `node.py --help` loads all of the node's imports, then exits.
    $launcher = Join-Path $PSScriptRoot "launcher.py"
    $script = Join-Path $Stage "$coin\node.py"
    $p = Start-Process -FilePath $PyExe -ArgumentList "`"$launcher`"", "script", "`"$script`"", "--help" -WorkingDirectory (Join-Path $Stage $coin) `
        -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $Build "$coin-smoke.txt")
    if (-not $p.WaitForExit(60000)) { $p.Kill(); Write-Host "$coin started (no --help); stopped it" }
    elseif ($p.ExitCode -ne 0) { throw "$coin node failed to start with the bundled Python" }
}

# 5. Compile the installer
$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $Iscc "/DAppVersion=$Version" "/DStageDir=$Stage" (Join-Path $PSScriptRoot "stellarite-node.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Write-Host "Built build\StellariteNode-Setup-$Version.exe" -ForegroundColor Yellow
