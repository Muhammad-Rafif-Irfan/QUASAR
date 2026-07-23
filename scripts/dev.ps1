<#
.SYNOPSIS
  Start QUASAR API (uvicorn) + frontend (Vite) for local demo.

.EXAMPLE
  .\scripts\dev.ps1
  .\scripts\dev.ps1 -SkipFrontend
#>
param(
    [switch]$SkipFrontend,
    [int]$ApiPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\pip.exe install -r requirements.txt
}

$env:QUASAR_ENV = if ($env:QUASAR_ENV) { $env:QUASAR_ENV } else { "development" }
$env:ALLOWED_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"

Write-Host "Starting API on http://127.0.0.1:$ApiPort ..."
$api = Start-Process -PassThru -NoNewWindow -FilePath ".\.venv\Scripts\uvicorn.exe" -ArgumentList @(
    "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "$ApiPort"
)

$fe = $null
try {
    if (-not $SkipFrontend) {
        if (-not (Test-Path "frontend\node_modules")) {
            Write-Host "Installing frontend deps (npm ci) ..."
            Push-Location frontend
            npm ci
            Pop-Location
        }
        Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort ..."
        $fe = Start-Process -PassThru -NoNewWindow -FilePath "npm" -ArgumentList @(
            "run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort"
        ) -WorkingDirectory (Join-Path $Root "frontend")
    }

    Write-Host ""
    Write-Host "API docs:  http://127.0.0.1:$ApiPort/docs"
    Write-Host "Health:    http://127.0.0.1:$ApiPort/health"
    if (-not $SkipFrontend) {
        Write-Host "Frontend:  http://127.0.0.1:$FrontendPort"
    }
    Write-Host "Press Ctrl+C to stop."
    Wait-Process -Id $api.Id
}
finally {
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
    if ($fe -and -not $fe.HasExited) { Stop-Process -Id $fe.Id -Force -ErrorAction SilentlyContinue }
}
