# One-command Windows installer (runs FolioOrb from source).
# Usage (PowerShell): irm https://raw.githubusercontent.com/udhawan97/FolioOrb/main/scripts/install-win.ps1 | iex
#
# Installs the latest stable release by default. Set $env:FOLIO_REF to a
# supported tag (v5.16.0+) or the dev channel: v5.16.1, latest-main, or main.
# Prefer the .exe for a no-Python install: https://github.com/udhawan97/FolioOrb/releases/latest
$ErrorActionPreference = "Stop"

$repo = "udhawan97/FolioOrb"
$defaultInstall = Join-Path $HOME "FolioOrb"
$defaultShortcut = Join-Path $HOME "Desktop\FolioOrb.lnk"
$defaultData = Join-Path $env:LOCALAPPDATA "FolioOrb-source"
$installDir = if ($env:FOLIOORB_INSTALL_DIR) { $env:FOLIOORB_INSTALL_DIR } else { $defaultInstall }
$shortcut = if ($env:FOLIOORB_SHORTCUT) { $env:FOLIOORB_SHORTCUT } else { $defaultShortcut }
$dataDir = if ($env:FOLIOORB_DATA_DIR) { $env:FOLIOORB_DATA_DIR } else { $defaultData }
$noStart = $env:FOLIOORB_INSTALL_NO_START -eq "1"

function Resolve-UserPath([string] $Value) {
    if ($Value -eq "~") { $Value = $HOME }
    elseif ($Value.StartsWith("~\") -or $Value.StartsWith("~/")) {
        $Value = Join-Path $HOME $Value.Substring(2)
    }
    return [System.IO.Path]::GetFullPath($Value)
}

$installDir = Resolve-UserPath $installDir
$shortcut = Resolve-UserPath $shortcut
$dataDir = Resolve-UserPath $dataDir
$migrationComplete = Join-Path $dataDir ".source-install-migration-complete"
$originalLocation = Get-Location
$tmp = $null
$rollbackDir = $null
$keepRecovery = $false
$installReady = $false

Write-Host ""
Write-Host "  FolioOrb Installer"
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
if ($ref -ne "main" -and $ref -ne "latest-main") {
    if ($ref -notmatch '^v(\d+)\.(\d+)\.(\d+)$' -or
        [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3]) -lt [version]"5.16.0") {
        throw "Source installs support stable tags v5.16.0 or newer; choose a supported tag, latest-main, or main."
    }
}
Write-Host "  Installing ref: $ref"

$releaseUrl = if ($ref -eq "main") {
    "https://github.com/$repo/archive/refs/heads/main.zip"
} else {
    "https://github.com/$repo/archive/refs/tags/$ref.zip"
}

# -- Python -------------------------------------------------------------------
function Find-Python {
    foreach ($cmd in @("py", "python", "python3")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            & $cmd -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $cmd }
        }
    }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "  Python not found. Installing via winget..."
        winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
        if (Get-Command python -ErrorAction SilentlyContinue) {
            & python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return "python" }
        }
    }
    return $null
}

$pythonCmd = Find-Python
if (-not $pythonCmd) {
    Write-Host "  Python 3.11+ is required."
    Start-Process "https://www.python.org/downloads/"
    throw "Python 3.11+ is required"
}
Write-Host "  OK $(& $pythonCmd --version)"

try {
    # -- Download --------------------------------------------------------------
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    Write-Host "  Downloading FolioOrb ($ref)..."
    Invoke-WebRequest $releaseUrl -OutFile (Join-Path $tmp "folio.zip") -UseBasicParsing
    Write-Host "  Extracting..."
    Expand-Archive (Join-Path $tmp "folio.zip") -DestinationPath $tmp
    $extracted = Get-ChildItem -Path $tmp -Directory -Filter "FolioOrb-*" | Select-Object -First 1
    if (-not $extracted) { throw "Download did not contain the expected FolioOrb folder." }

    # v5.16.0 predates the helper but already honors FOLIOORB_DATA_DIR.
    $migrationTool = Join-Path $extracted.FullName "scripts\migrate_source_profile.py"
    if (-not (Test-Path $migrationTool)) {
        $migrationTool = Join-Path $tmp "migrate_source_profile.py"
        Invoke-WebRequest "https://raw.githubusercontent.com/$repo/main/scripts/migrate_source_profile.py" `
            -OutFile $migrationTool -UseBasicParsing
    }

    # -- Preserve the complete writable profile -------------------------------
    $migrationOutput = & $pythonCmd $migrationTool --source $installDir --destination $dataDir
    if ($LASTEXITCODE -ne 0) { throw "Profile migration failed safely." }
    $migrationStatus = $migrationOutput | Select-Object -Last 1
    $keepRecovery = $migrationStatus -eq "MIGRATED"
    if ($keepRecovery) {
        Write-Host "  OK Portfolio, backups, settings, and update state migrated"
    }

    # -- Install transaction ---------------------------------------------------
    New-Item -ItemType Directory -Force -Path (Split-Path $installDir) | Out-Null
    if (Test-Path $installDir) {
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-$PID"
        $suffix = if ($keepRecovery) { "profile-recovery" } else { "update-rollback" }
        $rollbackDir = "$installDir-$suffix-$stamp"
        Move-Item $installDir $rollbackDir
    }
    Move-Item $extracted.FullName $installDir
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        (Join-Path $installDir ".source-profile-path"), "$dataDir`n", $utf8NoBom
    )
    $env:FOLIOORB_DATA_DIR = $dataDir

    Write-Host "  Installing dependencies (one-time, ~60 s)..."
    Set-Location $installDir
    & $pythonCmd -m venv venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
    $venvPy = Join-Path $installDir "venv\Scripts\python.exe"
    & $venvPy -m pip install --upgrade pip -q
    if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip." }
    & $venvPy -m pip install -r requirements.txt -q
    if ($LASTEXITCODE -ne 0) { throw "Could not install FolioOrb dependencies." }

    if (-not (Test-Path (Join-Path $dataDir ".env"))) {
        $secret = & $venvPy -c "import secrets; print(secrets.token_hex(32))"
        $environment = @"
ANTHROPIC_API_KEY=
SECRET_KEY=$secret
DEBUG=True
DATABASE_URL=sqlite:///./database/portfolio.db
CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
DEFAULT_HOLDINGS=
"@
        [System.IO.File]::WriteAllText((Join-Path $dataDir ".env"), $environment, $utf8NoBom)
    } elseif (-not (Select-String -Path (Join-Path $dataDir ".env") -Pattern '^\s*(export\s+)?SECRET_KEY\s*=' -Quiet)) {
        $secret = & $venvPy -c "import secrets; print(secrets.token_hex(32))"
        [System.IO.File]::AppendAllText(
            (Join-Path $dataDir ".env"), "SECRET_KEY=$secret`n", $utf8NoBom
        )
    }
    [System.IO.File]::WriteAllText(
        $migrationComplete, "source installer profile ready`n", $utf8NoBom
    )

    # A wrapper carries the external profile even when the selected tag predates
    # .source-profile-path support (notably v5.16.0).
    $cmdDataDir = $dataDir.Replace("%", "%%")
    $cmdInstallDir = $installDir.Replace("%", "%%")
    $launcher = Join-Path $installDir "FolioOrb-source.cmd"
    $launcherBody = "@echo off`r`nset `"FOLIOORB_DATA_DIR=$cmdDataDir`"`r`ncd /d `"$cmdInstallDir`"`r`ncall FolioOrb.bat`r`n"
    [System.IO.File]::WriteAllText($launcher, $launcherBody, $utf8NoBom)

    New-Item -ItemType Directory -Force -Path (Split-Path $shortcut) | Out-Null
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut($shortcut)
    $sc.TargetPath = $launcher
    $sc.WorkingDirectory = $installDir
    $sc.Description = "FolioOrb - Your folio, finally making sense."
    $sc.Save()

    if ($rollbackDir -and -not $keepRecovery) {
        Remove-Item $rollbackDir -Recurse -Force
        $rollbackDir = $null
    }
    $installReady = $true
} catch {
    if (-not $installReady -and $rollbackDir -and (Test-Path $rollbackDir)) {
        if (Test-Path $installDir) {
            Move-Item $installDir (Join-Path $tmp "failed-install-$PID") -Force -ErrorAction SilentlyContinue
        }
        if (-not (Test-Path $installDir)) {
            Move-Item $rollbackDir $installDir
        }
        Write-Error "Installation failed; the prior source install was restored. $($_.Exception.Message)"
    }
    throw
} finally {
    Set-Location $originalLocation
    if ($tmp -and (Test-Path $tmp)) {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "  OK Installed to $installDir"
Write-Host "  OK Writable profile: $dataDir"
if ($rollbackDir) { Write-Host "  OK Prior source install retained at $rollbackDir" }
Write-Host "  OK Desktop shortcut created at $shortcut"
Write-Host ""
if ($noStart) {
    Write-Host "  Start skipped for installer verification."
    exit 0
}
Write-Host "  Starting FolioOrb - your browser will open in a moment..."
Write-Host "  (Press Ctrl+C to stop)"
Write-Host ""
Set-Location $installDir
& $venvPy run.py
