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

function Import-LocalEnv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $name, $value = $line.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { return }
        # Explicit shell values win over the local .env file.
        if (-not (Test-Path "Env:$name")) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

Import-LocalEnv (Join-Path $Root ".env")

function Resolve-NpmCmd {
    $cmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($node) {
        $candidate = Join-Path (Split-Path $node.Source -Parent) "npm.cmd"
        if (Test-Path $candidate) { return $candidate }
    }
    throw "npm.cmd not found. Install Node.js and ensure it is on PATH."
}

function Test-PortInUse([int]$Port) {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        return $false
    } catch {
        return $true
    }
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\pip.exe install -r requirements.txt
}

$uvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $uvicorn)) {
    throw "uvicorn.exe missing in .venv. Run: .\.venv\Scripts\pip.exe install -r requirements.txt"
}

if (Test-PortInUse $ApiPort) {
    throw "Port $ApiPort already in use. Stop the old API process, then retry."
}
if (-not $SkipFrontend -and (Test-PortInUse $FrontendPort)) {
    throw "Port $FrontendPort already in use. Stop the old Vite process, then retry."
}

$env:QUASAR_ENV = if ($env:QUASAR_ENV) { $env:QUASAR_ENV } else { "development" }
$env:ALLOWED_ORIGINS = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"

Write-Host "Starting API on http://127.0.0.1:$ApiPort ..."
$api = Start-Process -PassThru -NoNewWindow -FilePath $uvicorn -ArgumentList @(
    "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "$ApiPort"
)

$fe = $null
$npmCmd = $null
try {
    if (-not $SkipFrontend) {
        $npmCmd = Resolve-NpmCmd
        if (-not (Test-Path "frontend\node_modules")) {
            Write-Host "Installing frontend deps (npm ci) ..."
            Push-Location frontend
            try {
                & $npmCmd ci
                if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit $LASTEXITCODE" }
            } finally {
                Pop-Location
            }
        }

        # On Windows, Start-Process cannot launch npm.ps1 ("not a valid Win32 application").
        # Always use npm.cmd (or node running vite directly).
        Write-Host "Starting frontend on http://127.0.0.1:$FrontendPort ..."
        $fe = Start-Process -PassThru -NoNewWindow -FilePath $npmCmd -ArgumentList @(
            "run", "dev", "--",
            "--host", "127.0.0.1",
            "--port", "$FrontendPort",
            "--strictPort"
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
    if ($null -ne $api -and -not $api.HasExited) {
        Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $fe -and -not $fe.HasExited) {
        Stop-Process -Id $fe.Id -Force -ErrorAction SilentlyContinue
    }
}
