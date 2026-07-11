[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [string]$AdbPath = 'adb',
    [string]$Serial = '127.0.0.1:15555',
    [int]$Samples = 10,
    [int]$IntervalMilliseconds = 2000,
    [int]$ExpectedWidth = 800,
    [int]$ExpectedHeight = 1280
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Drawing

if ($Samples -lt 2) {
    throw 'Samples must be at least 2 to evaluate freshness.'
}

if ($IntervalMilliseconds -lt 0) {
    throw 'IntervalMilliseconds cannot be negative.'
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

function Invoke-AdbText {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & $AdbPath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "ADB command failed ($LASTEXITCODE): adb $($Arguments -join ' ')`n$output"
    }

    return ($output | Out-String).Trim()
}

function Get-Percentile {
    param(
        [Parameter(Mandatory = $true)]
        [double[]]$Values,

        [Parameter(Mandatory = $true)]
        [double]$Percent
    )

    $sorted = @($Values | Sort-Object)
    $rank = ($Percent / 100) * ($sorted.Count - 1)
    $lower = [Math]::Floor($rank)
    $upper = [Math]::Ceiling($rank)

    if ($lower -eq $upper) {
        return [double]$sorted[$lower]
    }

    $fraction = $rank - $lower
    return [double]($sorted[$lower] + (($sorted[$upper] - $sorted[$lower]) * $fraction))
}

$state = Invoke-AdbText -Arguments @('-s', $Serial, 'get-state')
if ($state -ne 'device') {
    throw "ADB serial is not ready: $Serial ($state)"
}

$display = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'size')
$density = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'density')
$rotation = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'user-rotation')
$bootCompleted = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'getprop', 'sys.boot_completed')

$records = [System.Collections.Generic.List[object]]::new()
$previousHash = $null
$duplicateRun = 0
$maxDuplicateRun = 0

for ($index = 1; $index -le $Samples; $index++) {
    $path = Join-Path $OutputDirectory ('capture-{0:D3}.png' -f $index)
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process `
        -FilePath $AdbPath `
        -ArgumentList @('-s', $Serial, 'exec-out', 'screencap', '-p') `
        -RedirectStandardOutput $path `
        -NoNewWindow `
        -Wait `
        -PassThru
    $stopwatch.Stop()

    if ($process.ExitCode -ne 0) {
        throw "Screenshot capture failed for sample $index with exit $($process.ExitCode)."
    }

    $file = Get-Item -LiteralPath $path
    if ($file.Length -lt 8) {
        throw "Screenshot capture is too small for sample $index ($($file.Length) bytes)."
    }

    $image = [System.Drawing.Image]::FromFile($path)
    try {
        $width = $image.Width
        $height = $image.Height
    }
    finally {
        $image.Dispose()
    }

    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    $isDuplicate = $hash -eq $previousHash
    if ($isDuplicate) {
        $duplicateRun++
    }
    else {
        $duplicateRun = 0
    }

    $maxDuplicateRun = [Math]::Max($maxDuplicateRun, $duplicateRun)
    $records.Add([PSCustomObject]@{
        index = $index
        path = $file.Name
        sha256 = $hash
        width = $width
        height = $height
        bytes = $file.Length
        capture_ms = $stopwatch.Elapsed.TotalMilliseconds
        duplicate_of_previous = $isDuplicate
        valid_dimensions = ($width -eq $ExpectedWidth -and $height -eq $ExpectedHeight)
        modified = $file.LastWriteTime.ToString('o')
    })
    $previousHash = $hash

    if ($index -lt $Samples -and $IntervalMilliseconds -gt 0) {
        Start-Sleep -Milliseconds $IntervalMilliseconds
    }
}

$latencies = @($records | ForEach-Object { [double]$_.capture_ms })
$invalidDimensions = @($records | Where-Object { -not $_.valid_dimensions }).Count
$uniqueHashes = @($records | Select-Object -ExpandProperty sha256 -Unique).Count
$duplicateSamples = @($records | Where-Object { $_.duplicate_of_previous }).Count

$summary = [PSCustomObject]@{
    generated_at = (Get-Date).ToString('o')
    adb_path = $AdbPath
    serial = $Serial
    boot_completed = $bootCompleted
    display = $display
    density = $density
    rotation = $rotation
    expected_width = $ExpectedWidth
    expected_height = $ExpectedHeight
    samples = $Samples
    interval_ms = $IntervalMilliseconds
    valid_pngs = $records.Count
    invalid_dimensions = $invalidDimensions
    unique_hashes = $uniqueHashes
    duplicate_adjacent_samples = $duplicateSamples
    max_duplicate_run = $maxDuplicateRun
    latency_min_ms = [Math]::Round(($latencies | Measure-Object -Minimum).Minimum, 3)
    latency_p50_ms = [Math]::Round((Get-Percentile -Values $latencies -Percent 50), 3)
    latency_p95_ms = [Math]::Round((Get-Percentile -Values $latencies -Percent 95), 3)
    latency_max_ms = [Math]::Round(($latencies | Measure-Object -Maximum).Maximum, 3)
    freshness_observed = ($uniqueHashes -gt 1)
}

$records | Export-Csv -LiteralPath (Join-Path $OutputDirectory 'captures.csv') -NoTypeInformation -Encoding utf8
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'summary.json') -Encoding utf8

if ($invalidDimensions -ne 0) {
    throw "Capture fidelity failed: $invalidDimensions frame(s) have incorrect dimensions."
}

if ($uniqueHashes -lt 2) {
    throw 'Capture fidelity failed: all frames have the same hash.'
}

$summary
