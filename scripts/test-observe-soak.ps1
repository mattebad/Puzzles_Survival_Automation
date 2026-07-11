[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [string]$AdbPath = 'adb',
    [string]$Serial = '127.0.0.1:15555',
    [string]$SshTarget = 'root@nas.local',

    [ValidateSet('OpenSshKey', 'PlinkPassword')]
    [string]$AuthenticationMode = 'OpenSshKey',

    [string]$HostKeyFingerprint = 'f0:b5:ee:95:fb:d2:6c:e5:f5:bf:d2:86:67:9b:21:55',
    [string]$PasswordEnvironmentVariable = 'UNRAID_TEMP_PASSWORD',
    [string]$VmName = 'PnS-BlissOS-PoC',
    [string]$PackageName = 'com.global.ztmslg',
    [string]$ActivityName = 'com.games37.sdk.AtlasPluginDemoActivity',

    [ValidateRange(2, 24)]
    [int]$DurationHours = 4,

    [ValidateRange(5, 3600)]
    [int]$IntervalSeconds = 300,

    [ValidateRange(0, 100000)]
    [int]$MaxSamples = 0,

    [int]$ExpectedWidth = 800,
    [int]$ExpectedHeight = 1280,

    [ValidateRange(1, 4096)]
    [int]$MaxEvidenceMiB = 512,

    [ValidateRange(2, 1000)]
    [int]$MaxDuplicateRun = 12,

    [switch]$LaunchGame
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Drawing

if ($VmName.Contains("'")) {
    throw 'VM names containing a single quote are not supported.'
}

if ($SshTarget -notmatch '^(?<user>[^@]+)@(?<host>.+)$') {
    throw 'SshTarget must use user@host form.'
}

$sshUser = $Matches.user
$sshHost = $Matches.host
$plinkPath = $null
$sshArgs = @(
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=8',
    '-o', 'StrictHostKeyChecking=yes',
    $SshTarget
)
$transientPassword = $null

if ($AuthenticationMode -eq 'PlinkPassword') {
    $plinkPath = (Get-Command plink.exe -ErrorAction Stop).Source
    $transientPassword = [Environment]::GetEnvironmentVariable(
        $PasswordEnvironmentVariable,
        'Process'
    )
    if ([string]::IsNullOrEmpty($transientPassword)) {
        throw "Environment variable $PasswordEnvironmentVariable is not set in this process."
    }
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
$framesDirectory = Join-Path $outputRoot 'frames'
$hostDirectory = Join-Path $outputRoot 'host'
New-Item -ItemType Directory -Path $framesDirectory, $hostDirectory -Force | Out-Null

$recordsPath = Join-Path $outputRoot 'samples.jsonl'
$runLogPath = Join-Path $outputRoot 'run.log'
$startTime = Get-Date
$deadline = $startTime.AddHours($DurationHours)
$records = [System.Collections.Generic.List[object]]::new()
$tunnel = $null
$lastHash = $null
$duplicateRun = 0
$maxObservedDuplicateRun = 0
$adbFailures = 0
$invalidFrames = 0
$blackFrames = 0
$hostMetricFailures = 0
$nonForegroundSamples = 0
$runError = $null
$stopReason = 'duration'
$startupSystemControlUsed = $false

function Write-RunLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $line = '{0} {1}' -f (Get-Date).ToString('o'), $Message
    Add-Content -LiteralPath $runLogPath -Value $line -Encoding utf8
}

function Invoke-AdbText {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & $AdbPath @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "ADB command failed ($exitCode): adb $($Arguments -join ' ')`n$($output | Out-String)"
    }

    return ($output | Out-String).Trim()
}

function Capture-Png {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process `
        -FilePath $AdbPath `
        -ArgumentList @('-s', $Serial, 'exec-out', 'screencap', '-p') `
        -RedirectStandardOutput $Path `
        -NoNewWindow `
        -Wait `
        -PassThru
    $stopwatch.Stop()

    if ($process.ExitCode -ne 0) {
        throw "Screenshot capture failed with exit $($process.ExitCode)."
    }

    return $stopwatch.Elapsed.TotalMilliseconds
}

function Get-FrameHealth {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $file = Get-Item -LiteralPath $Path
    if ($file.Length -lt 8) {
        throw "PNG is too small: $($file.Length) bytes."
    }

    $image = [System.Drawing.Bitmap]::new($Path)
    try {
        $width = $image.Width
        $height = $image.Height
        $stepX = [Math]::Max(1, [Math]::Floor($width / 40))
        $stepY = [Math]::Max(1, [Math]::Floor($height / 40))
        $sampleCount = 0
        $darkCount = 0
        $lumaTotal = 0.0

        for ($y = 0; $y -lt $height; $y += $stepY) {
            for ($x = 0; $x -lt $width; $x += $stepX) {
                $pixel = $image.GetPixel($x, $y)
                $luma = (0.2126 * $pixel.R) + (0.7152 * $pixel.G) + (0.0722 * $pixel.B)
                $sampleCount++
                $lumaTotal += $luma
                if ($luma -lt 8) {
                    $darkCount++
                }
            }
        }
    }
    finally {
        $image.Dispose()
    }

    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $darkRatio = $darkCount / [double]$sampleCount
    return [PSCustomObject]@{
        width = $width
        height = $height
        bytes = $file.Length
        sha256 = $hash
        valid_dimensions = ($width -eq $ExpectedWidth -and $height -eq $ExpectedHeight)
        mostly_black = ($darkRatio -ge 0.98)
        dark_ratio = [Math]::Round($darkRatio, 6)
        mean_luma = [Math]::Round($lumaTotal / [double]$sampleCount, 3)
    }
}

function Invoke-RemoteObservation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    if ($AuthenticationMode -eq 'PlinkPassword') {
        $output = & $plinkPath `
            -batch `
            -ssh `
            -hostkey $HostKeyFingerprint `
            -l $sshUser `
            -pw $transientPassword `
            $sshHost `
            $Command 2>&1
    }
    else {
        $output = & ssh @sshArgs $Command 2>&1
    }

    return [PSCustomObject]@{
        exit_code = $LASTEXITCODE
        text = ($output | Out-String).Trim()
    }
}

function Start-AdbTunnel {
    if ($AuthenticationMode -eq 'PlinkPassword') {
        return Start-Process `
            -FilePath $plinkPath `
            -ArgumentList @(
                '-batch', '-ssh', '-hostkey', $HostKeyFingerprint,
                '-l', $sshUser, '-pw', $transientPassword,
                '-L', '15555:192.168.122.79:5555',
                '-N', $sshHost
            ) `
            -WindowStyle Hidden `
            -PassThru
    }

    $forwardArguments = @(
        '-N',
        '-L', '15555:192.168.122.79:5555'
    )
    $forwardArguments += $sshArgs[0..($sshArgs.Count - 2)]
    $forwardArguments += $SshTarget
    return Start-Process `
        -FilePath 'ssh.exe' `
        -ArgumentList $forwardArguments `
        -WindowStyle Hidden `
        -PassThru
}

function Stop-AdbTunnel {
    if ($script:tunnel -and -not $script:tunnel.HasExited) {
        Stop-Process -Id $script:tunnel.Id -Force -ErrorAction SilentlyContinue
    }
}

function Get-RemoteMetricCommand {
    return @'
set +e
printf '%s\n' '--- timestamp ---'
date -Is
printf '%s\n' '--- domain state ---'
virsh domstate '__VM_NAME__' 2>&1
printf '%s\n' '--- domain stats ---'
virsh domstats --state --cpu-total --balloon --block --interface '__VM_NAME__' 2>&1
printf '%s\n' '--- memory ---'
free -m 2>&1
printf '%s\n' '--- cache filesystem ---'
df -B1 /mnt/cache 2>&1
printf '%s\n' '--- sensors ---'
sensors 2>&1
printf '%s\n' '--- docker stats ---'
docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>&1
printf '%s\n' '--- VM address ---'
virsh domifaddr '__VM_NAME__' --source lease 2>&1
printf '%s\n' '--- listeners ---'
ss -lntp 2>&1
printf '%s\n' '--- GPU sample ---'
rm -f /tmp/pns-intel-gpu.json /tmp/pns-intel-gpu.stderr
timeout 4s intel_gpu_top -J -s 1000 -o /tmp/pns-intel-gpu.json >/dev/null 2>/tmp/pns-intel-gpu.stderr
cat /tmp/pns-intel-gpu.json 2>&1
cat /tmp/pns-intel-gpu.stderr 2>&1
rm -f /tmp/pns-intel-gpu.json /tmp/pns-intel-gpu.stderr
'@
}

function Get-EvidenceBytes {
    $files = Get-ChildItem -LiteralPath $outputRoot -Recurse -File -ErrorAction SilentlyContinue
    if (-not $files) {
        return 0L
    }

    return [long](($files | Measure-Object -Property Length -Sum).Sum)
}

function Wait-ForAdbDevice {
    param(
        [int]$TimeoutSeconds = 90
    )

    $limit = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            & $AdbPath connect $Serial 2>$null | Out-Null
            $state = (Invoke-AdbText -Arguments @('-s', $Serial, 'get-state')).Trim()
            $boot = (Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'getprop', 'sys.boot_completed')).Trim()
            if ($state -eq 'device' -and $boot -eq '1') {
                return
            }
        }
        catch {
            # Keep polling during ordinary ADB startup; caller records final failure.
        }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $limit)

    throw "ADB did not reach device/boot-complete within $TimeoutSeconds seconds."
}

try {
    Write-RunLog 'RT-012 observe-only soak started.'
    Write-RunLog "duration_hours=$DurationHours interval_seconds=$IntervalSeconds launch_game=$([bool]$LaunchGame)"

    $tunnel = Start-AdbTunnel
    Start-Sleep -Seconds 3
    Wait-ForAdbDevice

    $display = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'size')
    $density = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'density')
    $rotation = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'wm', 'user-rotation')
    $egl = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'getprop', 'ro.hardware.egl')
    if ($display -notmatch "Override size:\s+$ExpectedWidth`x$ExpectedHeight") {
        throw "Unexpected display profile: $display"
    }
    if ($density -notmatch '160') {
        throw "Unexpected density: $density"
    }
    if ($egl -notmatch 'mesa') {
        throw "Unexpected renderer: $egl"
    }

    $policy = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'dumpsys', 'window', 'policy')
    if ($policy -match 'mInputRestricted=true') {
        Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP') | Out-Null
        Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'input', 'keyevent', '82') | Out-Null
        Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'cmd', 'window', 'dismiss-keyguard') | Out-Null
        $startupSystemControlUsed = $true
        Start-Sleep -Seconds 2
    }

    if ($LaunchGame) {
        $launchOutput = Invoke-AdbText -Arguments @(
            '-s', $Serial, 'shell', 'am', 'start', '-W',
            '-n', "$PackageName/$ActivityName"
        )
        $launchOutput | Set-Content -LiteralPath (Join-Path $outputRoot 'game-launch.txt') -Encoding utf8
        Start-Sleep -Seconds 30
    }

    $sampleIndex = 0
    while ($sampleIndex -lt $MaxSamples -or ($MaxSamples -eq 0 -and (Get-Date) -lt $deadline)) {
        $sampleIndex++
        $sampleTime = Get-Date
        $frameName = 'frame-{0:D5}.png' -f $sampleIndex
        $framePath = Join-Path $framesDirectory $frameName
        $hostName = 'host-{0:D5}.txt' -f $sampleIndex
        $hostPath = Join-Path $hostDirectory $hostName
        $adbHealthy = $false
        $captureMs = $null
        $frame = $null
        $activity = $null
        $sampleError = $null

        try {
            & $AdbPath connect $Serial 2>$null | Out-Null
            $state = Invoke-AdbText -Arguments @('-s', $Serial, 'get-state')
            $boot = Invoke-AdbText -Arguments @('-s', $Serial, 'shell', 'getprop', 'sys.boot_completed')
            if ($state -ne 'device' -or $boot -ne '1') {
                throw "ADB state not ready: state=$state boot=$boot"
            }

            $adbHealthy = $true
            $captureMs = Capture-Png -Path $framePath
            $frame = Get-FrameHealth -Path $framePath
            if (-not $frame.valid_dimensions) {
                $invalidFrames++
            }
            if ($frame.mostly_black) {
                $blackFrames++
            }

            if ($frame.sha256 -eq $lastHash) {
                $duplicateRun++
            }
            else {
                $duplicateRun = 0
            }
            $maxObservedDuplicateRun = [Math]::Max($maxObservedDuplicateRun, $duplicateRun)
            $lastHash = $frame.sha256

            $activity = Invoke-AdbText -Arguments @(
                '-s', $Serial, 'shell', 'dumpsys', 'activity', 'top'
            )
            if ($LaunchGame -and $activity -notmatch [Regex]::Escape($PackageName)) {
                $nonForegroundSamples++
            }
        }
        catch {
            $adbFailures++
            $sampleError = $_.Exception.Message
            Write-RunLog "sample=$sampleIndex adb_error=$sampleError"
        }

        $remote = Invoke-RemoteObservation -Command (Get-RemoteMetricCommand).Replace(
            '__VM_NAME__',
            $VmName
        )
        $remote.text | Set-Content -LiteralPath $hostPath -Encoding utf8
        if ($remote.exit_code -ne 0) {
            $hostMetricFailures++
        }

        $record = [PSCustomObject]@{
            sample = $sampleIndex
            captured_at = $sampleTime.ToString('o')
            elapsed_seconds = [Math]::Round(($sampleTime - $startTime).TotalSeconds, 3)
            adb_healthy = $adbHealthy
            capture_ms = $captureMs
            frame = if ($frame) { [PSCustomObject]@{
                path = "frames/$frameName"
                width = $frame.width
                height = $frame.height
                bytes = $frame.bytes
                sha256 = $frame.sha256
                valid_dimensions = $frame.valid_dimensions
                mostly_black = $frame.mostly_black
                dark_ratio = $frame.dark_ratio
                mean_luma = $frame.mean_luma
                duplicate_run = $duplicateRun
            } } else { $null }
            game_foreground = if ($LaunchGame -and $activity) {
                ($activity -match [Regex]::Escape($PackageName))
            } else {
                $null
            }
            host_metrics = [PSCustomObject]@{
                path = "host/$hostName"
                exit_code = $remote.exit_code
            }
            error = $sampleError
        }
        $records.Add($record)
        ($record | ConvertTo-Json -Depth 8 -Compress) | Add-Content `
            -LiteralPath $recordsPath `
            -Encoding utf8

        $evidenceBytes = Get-EvidenceBytes
        if ($evidenceBytes -gt ($MaxEvidenceMiB * 1MB)) {
            $stopReason = 'evidence_quota'
            Write-RunLog "evidence quota reached: bytes=$evidenceBytes"
            break
        }

        if ($MaxSamples -gt 0 -and $sampleIndex -ge $MaxSamples) {
            $stopReason = 'max_samples'
            break
        }

        $nextSample = $startTime.AddSeconds($sampleIndex * $IntervalSeconds)
        $sleepSeconds = [Math]::Floor(($nextSample - (Get-Date)).TotalSeconds)
        if ($sleepSeconds -gt 0) {
            Start-Sleep -Seconds $sleepSeconds
        }
    }
}
catch {
    $runError = $_.Exception.Message
    $stopReason = 'error'
    Write-RunLog "run_error=$runError"
}
finally {
    try {
        & $AdbPath disconnect $Serial 2>$null | Out-Null
    }
    catch {
        # Cleanup must not hide the retained run result.
    }

    Stop-AdbTunnel
    $transientPassword = $null
    $endTime = Get-Date
    $durationCompleted = ($MaxSamples -eq 0 -and $endTime -ge $deadline -and $stopReason -eq 'duration')
    $uniqueHashes = @(
        $records |
            Where-Object { $_.frame -and $_.frame.sha256 } |
            ForEach-Object { $_.frame.sha256 } |
            Sort-Object -Unique
    ).Count
    $validFrames = @($records | Where-Object { $_.frame -and $_.frame.valid_dimensions }).Count
    $freshnessStale = ($maxObservedDuplicateRun -ge $MaxDuplicateRun)
    $allCriteria = (
        $durationCompleted -and
        $records.Count -gt 0 -and
        $adbFailures -eq 0 -and
        $invalidFrames -eq 0 -and
        $blackFrames -eq 0 -and
        $hostMetricFailures -eq 0 -and
        $nonForegroundSamples -eq 0 -and
        -not $freshnessStale
    )
    $summary = [PSCustomObject]@{
        generated_at = $endTime.ToString('o')
        started_at = $startTime.ToString('o')
        ended_at = $endTime.ToString('o')
        duration_hours_requested = $DurationHours
        duration_completed = $durationCompleted
        interval_seconds = $IntervalSeconds
        samples = $records.Count
        expected_width = $ExpectedWidth
        expected_height = $ExpectedHeight
        display = if (Get-Variable display -ErrorAction SilentlyContinue) { $display } else { $null }
        density = if (Get-Variable density -ErrorAction SilentlyContinue) { $density } else { $null }
        rotation = if (Get-Variable rotation -ErrorAction SilentlyContinue) { $rotation } else { $null }
        renderer = if (Get-Variable egl -ErrorAction SilentlyContinue) { $egl } else { $null }
        launch_game = [bool]$LaunchGame
        startup_system_control_used = $startupSystemControlUsed
        gameplay_input_sent = $false
        credential_or_tutorial_automation = $false
        adb_failures = $adbFailures
        invalid_frames = $invalidFrames
        black_frames = $blackFrames
        non_foreground_samples = $nonForegroundSamples
        host_metric_failures = $hostMetricFailures
        valid_frames = $validFrames
        unique_hashes = $uniqueHashes
        max_duplicate_run = $maxObservedDuplicateRun
        stale_frame_observed = $freshnessStale
        evidence_bytes = Get-EvidenceBytes
        evidence_quota_bytes = $MaxEvidenceMiB * 1MB
        stop_reason = $stopReason
        run_error = $runError
        manual_visual_review_required = $true
        all_automated_criteria_met = $allCriteria
    }
    $summary | ConvertTo-Json -Depth 8 | Set-Content `
        -LiteralPath (Join-Path $outputRoot 'summary.json') `
        -Encoding utf8
    @{
        mutation = $false
        gameplay_input = $false
        credentials = $false
        tutorial_automation = $false
        package = $PackageName
        vm_name = $VmName
        serial = $Serial
        output_directory = $outputRoot
    } | ConvertTo-Json | Set-Content `
        -LiteralPath (Join-Path $outputRoot 'session.json') `
        -Encoding utf8
}

if ($runError) {
    throw $runError
}

if (-not $allCriteria) {
    throw "Observe-only soak incomplete or failed. See $(Join-Path $outputRoot 'summary.json')."
}

$summary
