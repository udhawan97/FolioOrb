param(
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Get-PythonCommand {
    $candidates = @(
        @{ Command = "py"; Args = @("-3.12") },
        @{ Command = "py"; Args = @("-3.11") },
        @{ Command = "python"; Args = @() },
        @{ Command = "python3"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $command = $candidate.Command
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            continue
        }

        $args = $candidate.Args
        $versionCheck = "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        & $command @args -c $versionCheck | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = $command; Args = $args }
        }
    }

    return $null
}

$python = Get-PythonCommand
if ($null -eq $python) {
    Write-Host "Python 3.11+ is required. Install it from https://www.python.org/downloads/ and run this again."
    exit 1
}

& $python.Command @($python.Args + @("--version"))

if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..."
    & $python.Command @($python.Args + @("-m", "venv", "venv"))
}

$venvPython = Join-Path "venv" "Scripts\python.exe"

Write-Host "Installing dependencies..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

New-Item -ItemType Directory -Force -Path "database" | Out-Null

if (-not (Test-Path ".env")) {
    $secretKey = & $venvPython -c "import secrets; print(secrets.token_hex(32))"
    $anthropicKey = Read-Host "Anthropic API key for AI features (optional, press Enter to skip)"

    @"
ANTHROPIC_API_KEY=$anthropicKey
SECRET_KEY=$secretKey
DEBUG=True
DATABASE_URL=sqlite:///./database/portfolio.db
CORS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
DEFAULT_HOLDINGS=
"@ | Set-Content -Path ".env" -Encoding UTF8

    Write-Host "Created .env with local defaults."
} else {
    Write-Host "Using existing .env."
}

if ($NoStart) {
    Write-Host "Setup complete. Start the app with .\scripts\start.ps1"
    exit 0
}

Write-Host "Starting FolioOrb at http://localhost:8000"
& $venvPython run.py
