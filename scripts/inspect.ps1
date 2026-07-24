<#
.SYNOPSIS
  Inspect how QUASAR is running (API health, pipeline, recent runs, frontend).

.EXAMPLE
  .\scripts\inspect.ps1
  .\scripts\inspect.ps1 -ApiBase http://127.0.0.1:8000 -FrontendBase http://127.0.0.1:5173
#>
param(
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$FrontendBase = "http://127.0.0.1:5173"
)

$ErrorActionPreference = "Continue"

function Get-Json([string]$Url) {
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec 5
    } catch {
        return $null
    }
}

function Test-Http([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return $r.StatusCode
    } catch {
        return $null
    }
}

Write-Host "QUASAR inspect"
Write-Host "=============="
Write-Host "API base:      $ApiBase"
Write-Host "Frontend base: $FrontendBase"
Write-Host ""

$health = Get-Json "$ApiBase/health"
if ($null -eq $health) {
    Write-Host "[FAIL] API /health unreachable. Start with: .\scripts\dev.ps1"
    exit 1
}

Write-Host "[OK]   /health -> $($health.status) | db=$($health.checks.database) | quantum=$($health.checks.quantum_backend) | env=$($health.checks.environment)"

$inspect = Get-Json "$ApiBase/api/v1/inspect"
if ($null -eq $inspect) {
    Write-Host "[FAIL] /api/v1/inspect unreachable"
    exit 1
}

Write-Host "[OK]   /api/v1/inspect -> $($inspect.service) v$($inspect.version)"
Write-Host ""
Write-Host "How a request runs:"
foreach ($stage in $inspect.pipeline) {
    Write-Host ("  {0}. {1}" -f $stage.step, $stage.name)
    Write-Host ("     module: {0}" -f $stage.module)
    Write-Host ("     {0}" -f $stage.description)
}

Write-Host ""
Write-Host "Endpoints:"
foreach ($ep in $inspect.endpoints) {
    Write-Host "  - $ep"
}

Write-Host ""
if ($inspect.recent_runs.Count -eq 0) {
    Write-Host "Recent runs: (none yet)"
} else {
    Write-Host "Recent runs:"
    foreach ($run in $inspect.recent_runs) {
        Write-Host ("  - {0}  {1}  depot={2}  stops={3}" -f $run.run_id.Substring(0, [Math]::Min(8, $run.run_id.Length)), $run.status, $run.depot_name, $run.stops_count)
    }
}

Write-Host ""
Write-Host "Notes:"
foreach ($n in $inspect.notes) {
    Write-Host "  - $n"
}

Write-Host ""
$fe = Test-Http $FrontendBase
if ($null -eq $fe) {
    Write-Host "[WARN] Frontend not reachable at $FrontendBase (API-only is fine)."
} else {
    Write-Host "[OK]   Frontend HTTP $fe at $FrontendBase"
}

Write-Host ""
Write-Host "Docs: $ApiBase/docs"
Write-Host "Inspect JSON: $ApiBase/api/v1/inspect"
