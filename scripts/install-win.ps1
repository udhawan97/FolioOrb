# One-command Windows installer (runs FolioSenseAI from source).
# Usage (PowerShell): irm https://raw.githubusercontent.com/udhawan97/FolioSenseAI/main/scripts/install-win.ps1 | iex
#
# Installs the latest stable release by default. Set $env:FOLIO_REF to pin a tag
# or track the dev channel before running, e.g.:
#   $env:FOLIO_REF = "v4.3.1"       # a specific release
#   $env:FOLIO_REF = "latest-main"  # newest main build
#   $env:FOLIO_REF = "main"         # current main branch
#
# Prefer the .exe for a no-Python install: https://github.com/udhawan97/FolioSenseAI/releases/latest
$ErrorActionPreference = "Stop"

$repo        = "udhawan97/FolioSenseAI"
$installDir  = "$HOME\FolioSenseAI"
$shortcut    = "$HOME\Desktop\FolioSenseAI.lnk"

Write-Host ""
Write-Host "  FolioSenseAI Installer"
Write-Host "  ---------------------"
Write-Host ""

# -- Resolve which ref to download --------------------------------------------
$ref = $env:FOLIO_REF
if (-not $ref) {
    try {
        $latest = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -UseBasicParsing
        $ref = $latest.tag_name
    } catch { $ref = $null }
}
if (-not $ref) {
    Write-Host "  Could not resolve the latest release - falling back to 'main'."
    $ref = "main"
}
Write-Host "  Installing ref: $ref"

if ($ref -eq "main") {
    $releaseUrl = "https://github.com/$repo/archive/refs/heads/main.zip"
} else {
    $releaseUrl = "https://github.com/$repo/archive/refs/tags/$ref.zip"
}

# ── Python ────────────────────────────────────────────────────────────────────
function Find-Python {
    foreach ($cmd in @("py", "python", "python3")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $ok = & $cmd -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $cmd }
        }
    }
    # Try winget auto-install
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Python not found. Installing via winget..."
        winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path","User")
        if (Get-Command python -ErrorAction SilentlyContinue) {
            $ok = & python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return "python" }
        }
    }
    return $null
}

$pythonCmd = Find-Python
if (-not $pythonCmd) {
    Write-Host "  Python 3.11+ is required."
    Write-Host "  Opening the download page — install it (check 'Add Python to PATH'), then run this command again."
    Start-Process "https://www.python.org/downloads/"
    Read-Host "Press Enter to exit"
    exit 1
}
$pyVer = & $pythonCmd --version
Write-Host "  OK $pyVer"

# ── Download ──────────────────────────────────────────────────────────────────
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $tmp | Out-Null

Write-Host "  Downloading FolioSenseAI ($ref)..."
Invoke-WebRequest $releaseUrl -OutFile "$tmp\folio.zip" -UseBasicParsing

Write-Host "  Extracting..."
Expand-Archive "$tmp\folio.zip" -DestinationPath $tmp

# GitHub names the extracted folder after the ref (and strips a leading "v" on
# version tags), so locate it instead of guessing the name.
$extracted = Get-ChildItem -Path $tmp -Directory -Filter "FolioSenseAI-*" | Select-Object -First 1
if (-not $extracted) {
    Write-Host "  Download did not contain the expected FolioSenseAI folder."
    exit 1
}

# ── Preserve existing data ────────────────────────────────────────────────────
if (Test-Path "$installDir\database") {
    Write-Host "  Existing portfolio found - preserving your data..."
    Copy-Item "$installDir\database" "$tmp\db_backup" -Recurse
}
if (Test-Path "$installDir\.env") {
    Copy-Item "$installDir\.env" "$tmp\env_backup"
}

# ── Install ───────────────────────────────────────────────────────────────────
if (Test-Path $installDir) { Remove-Item $installDir -Recurse -Force }
Move-Item $extracted.FullName $installDir

if (Test-Path "$tmp\env_backup") {
    Copy-Item "$tmp\env_backup" "$installDir\.env"
    Write-Host "  OK Settings restored"
}

# Restore database before pip so data is safe even if dependency install fails.
if (Test-Path "$tmp\db_backup") {
    if (Test-Path "$installDir\database") { Remove-Item "$installDir\database" -Recurse -Force }
    Copy-Item "$tmp\db_backup" "$installDir\database" -Recurse
    Write-Host "  OK Portfolio data restored"
} else {
    New-Item -ItemType Directory -Force -Path "$installDir\database" | Out-Null
}

# ── Dependencies ──────────────────────────────────────────────────────────────
Write-Host "  Installing dependencies (one-time, ~60 s)..."
Set-Location $installDir
& $pythonCmd -m venv venv
$venvPy = "$installDir\venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip -q
& $venvPy -m pip install -r requirements.txt -q

Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

if (-not (Test-Path ".env")) {
    $secret = & $venvPy -c "import secrets; print(secrets.token_hex(32))"
    @"
ANTHROPIC_API_KEY=
SECRET_KEY=$secret
DEBUG=True
DATABASE_URL=sqlite:///./database/portfolio.db
CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
DEFAULT_HOLDINGS=
"@ | Set-Content -Path ".env" -Encoding UTF8
}

# ── Desktop shortcut ─────────────────────────────────────────────────────────
$wsh = New-Object -ComObject WScript.Shell
$sc  = $wsh.CreateShortcut($shortcut)
$sc.TargetPath       = "$installDir\FolioSenseAI.bat"
$sc.WorkingDirectory = $installDir
$sc.Description      = "FolioSenseAI — Your folio, finally making sense."
$sc.Save()

Write-Host ""
Write-Host "  OK Installed to $installDir"
Write-Host "  OK Desktop shortcut created — double-click it anytime to open the app"
Write-Host ""
Write-Host "  Starting FolioSenseAI — your browser will open in a moment..."
Write-Host "  (Press Ctrl+C to stop)"
Write-Host ""
& $venvPy run.py
