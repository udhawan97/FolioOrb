$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$venvPython = Join-Path "venv" "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No virtual environment found. Run .\scripts\setup.ps1 first."
    exit 1
}

New-Item -ItemType Directory -Force -Path "database" | Out-Null

Write-Host "Starting FolioOrb at http://localhost:8000"
& $venvPython run.py
