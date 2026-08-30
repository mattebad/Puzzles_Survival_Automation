param(
    [string]$Prompt
)

$ErrorActionPreference = "Stop"
$benchmarkRoot = "C:\Users\burni\Documents\Qwen38_Benchmarking"
$serverLauncher = Join-Path $benchmarkRoot "Start-Qwen38-Production.ps1"
$ompLauncher = Join-Path $benchmarkRoot "Start-OMP-PS.ps1"
$endpoint = "http://127.0.0.1:1235"

if (-not (Test-Path -LiteralPath $serverLauncher -PathType Leaf)) {
    throw "Production server launcher is missing: $serverLauncher"
}
if (-not (Test-Path -LiteralPath $ompLauncher -PathType Leaf)) {
    throw "Production OMP launcher is missing: $ompLauncher"
}

$healthy = $false
try {
    $health = Invoke-RestMethod -Uri "$endpoint/health" -TimeoutSec 5
    $healthy = $health.status -eq "ok"
} catch {
    $healthy = $false
}

if (-not $healthy) {
    Write-Host "Qwen3.8 production server is not running; starting it now."
    & $serverLauncher
}
else {
    Write-Host "Qwen3.8 production server is already healthy."
}

if ($Prompt) {
    & $ompLauncher -Repository $PSScriptRoot -Prompt $Prompt
}
else {
    & $ompLauncher -Repository $PSScriptRoot
}
exit $LASTEXITCODE
