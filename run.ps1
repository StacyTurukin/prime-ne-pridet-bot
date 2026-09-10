$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $python = $null

    $siblingPython = Join-Path (Split-Path -Parent $PSScriptRoot) "BroNeSkufBot\.venv\Scripts\python.exe"
    if (Test-Path $siblingPython) {
        $python = $siblingPython
        Write-Host "Using Python from BroNeSkufBot." -ForegroundColor Cyan
    }

    if (-not $python) {
        $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($cmd) { $python = $cmd.Source }
    }

    if (-not $python) { throw "Python was not found." }

    & $python -m venv .venv
}

$venvPython = ".\.venv\Scripts\python.exe"

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ""
    Write-Host "Created .env. Add BOT_TOKEN and ADMIN_USER_ID, then run .\run.ps1 again." -ForegroundColor Yellow
    exit 0
}

& $venvPython -m app.main
