[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VmName,

    [string]$SshTarget = 'root@nas.local',

    [ValidateSet('OpenSshKey', 'PlinkPassword')]
    [string]$AuthenticationMode = 'OpenSshKey',

    [string]$HostKeyFingerprint = 'f0:b5:ee:95:fb:d2:6c:e5:f5:bf:d2:86:67:9b:21:55',

    [string]$PasswordEnvironmentVariable = 'UNRAID_TEMP_PASSWORD',

    [string]$OutputRoot = (Join-Path $PSScriptRoot '..\evidence\sessions')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputDir = Join-Path $OutputRoot "$stamp-rt-001-baseline"
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$sshArgs = @(
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=8',
    '-o', 'StrictHostKeyChecking=yes',
    $SshTarget
)

$plinkPath = $null
$plinkUser = $null
$plinkHost = $null
$transientPassword = $null
if ($AuthenticationMode -eq 'PlinkPassword') {
    if ($SshTarget -notmatch '^(?<user>[^@]+)@(?<host>.+)$') {
        throw 'PlinkPassword mode requires SshTarget in user@host form.'
    }
    $plinkUser = $Matches.user
    $plinkHost = $Matches.host
    $plinkPath = (Get-Command plink.exe -ErrorAction Stop).Source
    $transientPassword = [Environment]::GetEnvironmentVariable($PasswordEnvironmentVariable, 'Process')
    if ([string]::IsNullOrEmpty($transientPassword)) {
        throw "Environment variable $PasswordEnvironmentVariable is not set in this process."
    }
}

function Invoke-ReadOnlyRemote {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Command
    )

    $path = Join-Path $outputDir "$Name.txt"
    if ($AuthenticationMode -eq 'PlinkPassword') {
        $result = & $plinkPath -batch -ssh -hostkey $HostKeyFingerprint -l $plinkUser -pw $transientPassword $plinkHost $Command 2>&1
    }
    else {
        $result = & ssh @sshArgs $Command 2>&1
    }
    $exitCode = $LASTEXITCODE
    $result | Set-Content -LiteralPath $path -Encoding utf8
    if ($exitCode -ne 0) {
        throw "Remote read-only command '$Name' failed with exit code $exitCode. See $path"
    }
}

# Static commands only: this collector does not start, stop, define, or modify anything.
Invoke-ReadOnlyRemote 'host' 'hostname; date -Is; uname -a; virsh version; virsh nodeinfo'
Invoke-ReadOnlyRemote 'domains' 'virsh list --all'
Invoke-ReadOnlyRemote 'resources' 'free -h; df -h /mnt/cache 2>&1 || true; sensors 2>&1 || true'
Invoke-ReadOnlyRemote 'graphics' 'ls -l /dev/dri 2>&1; lspci -nnk | grep -A3 -Ei "vga|display"; dmesg | grep -Ei "i915|drm|gpu.*reset" | tail -n 200'
Invoke-ReadOnlyRemote 'services' 'docker stats --no-stream 2>&1; virsh domstats --state --cpu-total --balloon --block --interface'

if ($VmName.Contains("'")) {
    throw 'VM names containing a single quote are not supported by this collector.'
}
$escapedVmName = "'$VmName'"
Invoke-ReadOnlyRemote 'domain-info' "virsh dominfo $escapedVmName"
Invoke-ReadOnlyRemote 'domain-blocks' "virsh domblklist --details $escapedVmName"
Invoke-ReadOnlyRemote 'domain-network' "virsh domiflist $escapedVmName; virsh domifaddr $escapedVmName --source lease 2>&1 || true"
Invoke-ReadOnlyRemote 'domain-xml-inactive' "virsh dumpxml --inactive $escapedVmName"
Invoke-ReadOnlyRemote 'domain-xml-live' "virsh dumpxml $escapedVmName 2>&1 || true"
Invoke-ReadOnlyRemote 'domain-logs' "virsh domstate $escapedVmName; journalctl -u libvirtd -u virtqemud --since '-2 hours' --no-pager 2>&1 | tail -n 500"

$manifest = Get-ChildItem -LiteralPath $outputDir -File | Sort-Object Name | ForEach-Object {
    [PSCustomObject]@{
        path   = $_.Name
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes  = $_.Length
    }
}
$manifest | Export-Csv -LiteralPath (Join-Path $outputDir 'manifest.csv') -NoTypeInformation -Encoding utf8

@{
    collected_at = (Get-Date).ToString('o')
    ssh_target   = $SshTarget
    vm_name      = $VmName
    authentication_mode = $AuthenticationMode
    mutation     = $false
    purpose      = 'RT-001 read-only rollback baseline collection'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDir 'session.json') -Encoding utf8

Write-Output $outputDir

$transientPassword = $null
