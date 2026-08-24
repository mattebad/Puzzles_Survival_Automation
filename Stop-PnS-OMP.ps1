$ErrorActionPreference = "Stop"

$benchmarkRoot = "C:\Users\burni\Documents\Qwen38_Benchmarking"
$receiptPath = Join-Path $benchmarkRoot "logs\production\production-server-current.json"
$expectedExecutable = Join-Path $benchmarkRoot "native-llama-b10603\llama-server.exe"
$port = 1235

$targetPid = $null
if (Test-Path -LiteralPath $receiptPath -PathType Leaf) {
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $targetPid = [int]$receipt.pid
}
else {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $targetPid = [int]$listener.OwningProcess
    }
}

if (-not $targetPid) {
    Write-Host "Qwen3.8 production server is already stopped."
    exit 0
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId=$targetPid" -ErrorAction SilentlyContinue
if (-not $process) {
    Write-Host "Qwen3.8 production server is already stopped (stale receipt PID $targetPid)."
    exit 0
}

if (
    $process.ExecutablePath -ne $expectedExecutable -or
    $process.CommandLine -notmatch "--port\s+1235(?:\s|$)" -or
    $process.CommandLine -notmatch "--alias\s+qwen3\.8-27b@iq3_xxs(?:\s|$)"
) {
    throw "Refusing to stop PID $targetPid because it is not the pinned Qwen3.8 production server."
}

Stop-Process -Id $targetPid -Force
Wait-Process -Id $targetPid -Timeout 15 -ErrorAction SilentlyContinue

$stillRunning = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
if ($stillRunning) {
    throw "Qwen3.8 production server PID $targetPid did not stop."
}

Write-Host "Stopped Qwen3.8 production server PID $targetPid. GPU model memory is unloaded."
