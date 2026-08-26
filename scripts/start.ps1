$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $env:FOLIOORB_DATA_DIR -and (Test-Path ".source-profile-path")) {
    $env:FOLIOORB_DATA_DIR = (Get-Content ".source-profile-path" -Raw).Trim()
}
$profileDir = if ($env:FOLIOORB_DATA_DIR) { $env:FOLIOORB_DATA_DIR } else { "." }

$venvPython = Join-Path "venv" "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No virtual environment found. Run .\scripts\setup.ps1 first."
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $profileDir "database") | Out-Null

Write-Host "Starting FolioOrb at http://localhost:8000"
& $venvPython run.py
