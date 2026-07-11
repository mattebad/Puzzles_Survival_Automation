[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [string]$AdbPath = 'adb',
    [string]$Serial = '127.0.0.1:15555',
    [int]$ExpectedWidth = 800,
    [int]$ExpectedHeight = 1280,
    [int]$TolerancePixels = 8,
    [int]$SettlingMilliseconds = 250
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Drawing

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

function Capture-Png {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $process = Start-Process `
        -FilePath $AdbPath `
        -ArgumentList @('-s', $Serial, 'exec-out', 'screencap', '-p') `
        -RedirectStandardOutput $Path `
        -NoNewWindow `
        -Wait `
        -PassThru

    if ($process.ExitCode -ne 0) {
        throw "Screenshot capture failed with exit $($process.ExitCode)."
    }
}

function Get-ImageDimensions {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $image = [System.Drawing.Image]::FromFile($Path)
    try {
        return [PSCustomObject]@{
            width = $image.Width
            height = $image.Height
        }
    }
    finally {
        $image.Dispose()
    }
}

function Find-RedPointerMarker {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedX,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedY,

        [Parameter(Mandatory = $true)]
        [int]$Tolerance
    )

    $bitmap = [System.Drawing.Bitmap]::new($Path)
    try {
        $points = [System.Collections.Generic.List[object]]::new()
        $minX = [Math]::Max(0, $ExpectedX - $Tolerance)
        $maxX = [Math]::Min($bitmap.Width - 1, $ExpectedX + $Tolerance)
        $minY = [Math]::Max(0, $ExpectedY - $Tolerance)
        $maxY = [Math]::Min($bitmap.Height - 1, $ExpectedY + $Tolerance)

        for ($y = $minY; $y -le $maxY; $y++) {
            for ($x = $minX; $x -le $maxX; $x++) {
                $pixel = $bitmap.GetPixel($x, $y)
                if ($pixel.R -ge 120 -and $pixel.G -le 100 -and $pixel.B -le 130 -and $pixel.R -ge ($pixel.G + 60)) {
                    $points.Add([PSCustomObject]@{
                        x = $x
                        y = $y
                    })
                }
            }
        }

        if ($points.Count -eq 0) {
            return [PSCustomObject]@{
                detected = $false
                marker_pixels = 0
                measured_x = $null
                measured_y = $null
                error_pixels = $null
            }
        }

        $measuredX = ($points | Measure-Object -Property x -Average).Average
        $measuredY = ($points | Measure-Object -Property y -Average).Average
        $error = [Math]::Sqrt(
            [Math]::Pow($measuredX - $ExpectedX, 2) +
            [Math]::Pow($measuredY - $ExpectedY, 2)
        )

        return [PSCustomObject]@{
            detected = ($error -le $Tolerance)
            marker_pixels = $points.Count
            measured_x = [Math]::Round($measuredX, 3)
            measured_y = [Math]::Round($measuredY, 3)
            error_pixels = [Math]::Round($error, 3)
        }
    }
    finally {
        $bitmap.Dispose()
    }
}

$state = Invoke-AdbText -Arguments @('-s', $Serial, 'get-state')
if ($state -ne 'device') {
    throw "ADB serial is not ready: $Serial ($state)"
}

$display = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'size')
$density = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'density')
$rotation = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'user-rotation')
$pointerBefore = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'settings', 'get', 'system', 'pointer_location')

$tapTests = @(
    @{ type = 'tap'; name = 'tap-001'; start_x = 100; start_y = 200; end_x = 100; end_y = 200; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-002'; start_x = 400; start_y = 200; end_x = 400; end_y = 200; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-003'; start_x = 700; start_y = 200; end_x = 700; end_y = 200; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-004'; start_x = 100; start_y = 600; end_x = 100; end_y = 600; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-005'; start_x = 400; start_y = 600; end_x = 400; end_y = 600; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-006'; start_x = 700; start_y = 600; end_x = 700; end_y = 600; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-007'; start_x = 100; start_y = 1000; end_x = 100; end_y = 1000; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-008'; start_x = 400; start_y = 1000; end_x = 400; end_y = 1000; direction = 'point'; distance_class = 'point' },
    @{ type = 'tap'; name = 'tap-009'; start_x = 700; start_y = 1000; end_x = 700; end_y = 1000; direction = 'point'; distance_class = 'point' }
)

$swipeTests = @(
    @{ type = 'swipe'; name = 'swipe-001'; start_x = 200; start_y = 250; end_x = 200; end_y = 650; direction = 'down'; distance_class = 'long' },
    @{ type = 'swipe'; name = 'swipe-002'; start_x = 600; start_y = 850; end_x = 600; end_y = 450; direction = 'up'; distance_class = 'long' },
    @{ type = 'swipe'; name = 'swipe-003'; start_x = 250; start_y = 600; end_x = 550; end_y = 600; direction = 'right'; distance_class = 'long' },
    @{ type = 'swipe'; name = 'swipe-004'; start_x = 550; start_y = 850; end_x = 250; end_y = 850; direction = 'left'; distance_class = 'long' }
)

$tests = @($tapTests + $swipeTests)
$results = [System.Collections.Generic.List[object]]::new()

try {
    Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'input', 'keyevent', 'HOME') | Out-Null
    Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'settings', 'put', 'system', 'pointer_location', '1') | Out-Null
    $pointerAfterEnable = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'settings', 'get', 'system', 'pointer_location')

    foreach ($test in $tests) {
        if ($test.type -eq 'tap') {
            Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'input', 'tap', $test.end_x, $test.end_y) | Out-Null
        }
        else {
            Invoke-AdbText -Arguments @(
                '-s', $Serial,
                'shell', 'input', 'swipe',
                $test.start_x, $test.start_y,
                $test.end_x, $test.end_y,
                600
            ) | Out-Null
        }

        Start-Sleep -Milliseconds $SettlingMilliseconds
        $path = Join-Path $OutputDirectory "$($test.name).png"
        Capture-Png -Path $path
        $dimensions = Get-ImageDimensions -Path $path
        $marker = Find-RedPointerMarker `
            -Path $path `
            -ExpectedX $test.end_x `
            -ExpectedY $test.end_y `
            -Tolerance $TolerancePixels

        $results.Add([PSCustomObject]@{
            name = $test.name
            type = $test.type
            start_x = $test.start_x
            start_y = $test.start_y
            end_x = $test.end_x
            end_y = $test.end_y
            direction = $test.direction
            distance_class = $test.distance_class
            width = $dimensions.width
            height = $dimensions.height
            dimensions_valid = ($dimensions.width -eq $ExpectedWidth -and $dimensions.height -eq $ExpectedHeight)
            marker_detected = $marker.detected
            marker_pixels = $marker.marker_pixels
            measured_x = $marker.measured_x
            measured_y = $marker.measured_y
            error_pixels = $marker.error_pixels
            sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        })

        if ($test.type -eq 'swipe') {
            Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'input', 'keyevent', 'HOME') | Out-Null
        }
    }
}
finally {
    Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'settings', 'put', 'system', 'pointer_location', '0') | Out-Null
    Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'input', 'keyevent', 'HOME') | Out-Null
}

$pointerAfterReset = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'settings', 'get', 'system', 'pointer_location')
$invalidDimensions = @($results | Where-Object { -not $_.dimensions_valid }).Count
$undetectedMarkers = @($results | Where-Object { -not $_.marker_detected }).Count
$maxError = ($results | Measure-Object -Property error_pixels -Maximum).Maximum

$results | Export-Csv -LiteralPath (Join-Path $OutputDirectory 'results.csv') -NoTypeInformation -Encoding utf8
$summary = [PSCustomObject]@{
    generated_at = (Get-Date).ToString('o')
    serial = $Serial
    display = $display
    density = $density
    rotation = $rotation
    pointer_location_before = $pointerBefore
    pointer_location_after_enable = $pointerAfterEnable
    pointer_location_after_reset = $pointerAfterReset
    taps = @($results | Where-Object { $_.type -eq 'tap' }).Count
    swipes = @($results | Where-Object { $_.type -eq 'swipe' }).Count
    invalid_dimensions = $invalidDimensions
    undetected_markers = $undetectedMarkers
    max_error_pixels = [Math]::Round([double]$maxError, 3)
    tolerance_pixels = $TolerancePixels
    all_passed = ($invalidDimensions -eq 0 -and $undetectedMarkers -eq 0 -and $pointerAfterReset -eq '0')
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'summary.json') -Encoding utf8

if (-not $summary.all_passed) {
    throw "Input fidelity failed: invalid_dimensions=$invalidDimensions undetected_markers=$undetectedMarkers pointer_reset=$pointerAfterReset"
}

$summary
