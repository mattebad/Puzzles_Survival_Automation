#Requires -Version 5.1
<#
.SYNOPSIS
  Export a sanitized review snapshot from the local Git checkout.

.DESCRIPTION
  Exports committed source files (and optionally an explicit uncommitted allowlist) while
  hard-denying .git/, evidence/ (by default), local captures, secrets, caches, and archives.
  Exclusion of .git/, .local-captures/, and evidence/ is intentional review-snapshot policy,
  not a claim that those directories are missing from the checkout.
#>
[CmdletBinding()]
param(
  [string]$OutputDirectory = "",
  [string[]]$IncludeUncommitted = @(),
  [switch]$EvidenceSummaryMode,
  [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  $root = (git rev-parse --show-toplevel 2>$null)
  if (-not $root) { throw "Must run inside a Git checkout." }
  return (Resolve-Path $root).Path
}

function Get-RelativePath([string]$Root, [string]$FullPath) {
  $rootFull = (Resolve-Path $Root).Path.TrimEnd('\', '/')
  $full = (Resolve-Path $FullPath).Path
  if ($full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $full.Substring($rootFull.Length).TrimStart('\', '/').Replace('\', '/')
  }
  throw "Path escapes repository root: $FullPath"
}

function Test-DeniedPath([string]$RelativePath, [bool]$AllowEvidenceSummary) {
  $p = $RelativePath.Replace('\', '/')
  $deniedPrefixes = @(
    '.git/',
    '.local-reference/',
    '.local-captures/',
    '.local-orchestrator/',
    '.specstory/',
    '.vscode/',
    '.pytest_cache/',
    '.ruff_cache/',
    '.mypy_cache/',
    'artifacts/evidence-audit'
  )
  foreach ($prefix in $deniedPrefixes) {
    if ($p -eq $prefix.TrimEnd('/') -or $p.StartsWith($prefix)) { return $true }
  }
  if ($p -match '(^|/|)__pycache__(/|$)') { return $true }
  if ($p -match '\.(env|pem|key|p12|pfx)(\.|$)') { return $true }
  if ($p -match '(^|/)\.env(\..*)?$') { return $true }
  if ($p -match '\.(zip|7z)$') { return $true }
  if ($p -match '\.(sqlite3-wal|sqlite3-shm|mp4|mov|avi)$') { return $true }
  if ($p -match '(^|/)Puzzle_Survival_Runtime_POC.*\.zip$') { return $true }
  if ($p.StartsWith('evidence/')) {
    if (-not $AllowEvidenceSummary) { return $true }
    $name = [System.IO.Path]::GetFileName($p)
    $allowed = $false
    if ($name -eq 'current-evidence-manifest.json') { $allowed = $true }
    if ($name -like '*-evidence-manifest.json') { $allowed = $true }
    if ($name -like '*summary*.md') { $allowed = $true }
    if ($name -like '*manifest*.json' -and $p -notmatch '/raw/|/sessions/.+/frames/') { $allowed = $true }
    if (-not $allowed) { return $true }
  }
  return $false
}

function Test-SecretIndicators([string]$Text, [string]$MemberName) {
  # Reject assignment/use of denied credential names without printing values.
  $patterns = @(
    'UNRAID_TEMP_USERNAME\s*[:=]',
    'UNRAID_TEMP_PASSWORD\s*[:=]',
    'BEGIN RSA PRIVATE KEY',
    'BEGIN OPENSSH PRIVATE KEY',
    'BEGIN EC PRIVATE KEY',
    'AKIA[0-9A-Z]{16}'
  )
  foreach ($pattern in $patterns) {
    if ($Text -match $pattern) {
      throw "Secret indicator detected in archive member '$MemberName' (value redacted)."
    }
  }
  # Fixture/regression: bare denied variable names in dedicated fixture files are rejected.
  if ($MemberName -match 'review_snapshot_secret_names' -and ($Text -match 'UNRAID_TEMP_USERNAME' -or $Text -match 'UNRAID_TEMP_PASSWORD')) {
    throw "Secret indicator detected in archive member '$MemberName' (value redacted)."
  }
}

$repoRoot = Get-RepoRoot
Set-Location $repoRoot
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
$head = (git rev-parse HEAD).Trim()
if (-not $OutputDirectory) {
  $OutputDirectory = Join-Path $repoRoot '.local-orchestrator/review-exports'
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMddTHHmmssfffZ'
$exportName = "pns-review-snapshot-$branch-$($head.Substring(0,12))-$stamp"
$staging = Join-Path $OutputDirectory "$exportName-staging"
$zipPath = Join-Path $OutputDirectory "$exportName.zip"
$manifestPath = Join-Path $OutputDirectory "$exportName.manifest.json"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$files = @()
$tracked = git ls-files -z
if ($tracked) {
  $tracked.Split([char]0) | Where-Object { $_ -ne '' } | ForEach-Object { $files += $_ }
}
foreach ($item in $IncludeUncommitted) {
  $rel = $item.Replace('\', '/')
  if (-not (Test-Path (Join-Path $repoRoot $rel))) {
    throw "Allowlisted uncommitted path missing: $rel"
  }
  if ($files -notcontains $rel) { $files += $rel }
}
$files = $files | Sort-Object -Unique

$copied = @()
$deniedSkipped = @()
$uncompressed = [int64]0
foreach ($rel in $files) {
  if (Test-DeniedPath -RelativePath $rel -AllowEvidenceSummary:$EvidenceSummaryMode) {
    $deniedSkipped += $rel
    continue
  }
  $src = Join-Path $repoRoot $rel
  if (-not (Test-Path $src -PathType Leaf)) { continue }
  $dest = Join-Path $staging $rel
  $destDir = Split-Path $dest -Parent
  New-Item -ItemType Directory -Force -Path $destDir | Out-Null
  Copy-Item -LiteralPath $src -Destination $dest -Force
  $copied += $rel
  $uncompressed += (Get-Item -LiteralPath $src).Length
  if ($rel -match '\.(md|txt|py|json|yml|yaml|toml|ps1|sh|env)$') {
    $text = Get-Content -LiteralPath $src -Raw -ErrorAction SilentlyContinue
    if ($null -ne $text) { Test-SecretIndicators -Text $text -MemberName $rel }
  }
}

# Intentional policy exclusions (not missing content).
$policyExclusions = @(
  '.git/** (repository metadata; intentionally excluded from review snapshots)',
  '.local-captures/** (local bulk captures; intentionally excluded)',
  'evidence/** (authoritative local evidence tree; excluded by default; optional evidence-summary mode allowlists manifests/summaries only)'
)

if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
if (-not $DryRun) {
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::CreateFromDirectory($staging, $zipPath)
  $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
  try {
    foreach ($entry in $zip.Entries) {
      $name = $entry.FullName.Replace('\', '/')
      if (Test-DeniedPath -RelativePath $name -AllowEvidenceSummary:$EvidenceSummaryMode) {
        throw "Denied path appeared in final archive: $name"
      }
      if ($name -match '\.(md|txt|py|json|yml|yaml|toml|ps1|sh)$' -and $entry.Length -gt 0 -and $entry.Length -lt 5MB) {
        $reader = New-Object System.IO.StreamReader($entry.Open())
        try {
          $text = $reader.ReadToEnd()
          Test-SecretIndicators -Text $text -MemberName $name
        } finally {
          $reader.Dispose()
        }
      }
    }
  } finally {
    $zip.Dispose()
  }
}

$manifest = [ordered]@{
  schema_version = 1
  source_branch = $branch
  source_head = $head
  output_zip = if ($DryRun) { $null } else { (Get-RelativePath $repoRoot $zipPath) }
  file_count = $copied.Count
  uncompressed_bytes = $uncompressed
  compressed_bytes = if ((-not $DryRun) -and (Test-Path $zipPath)) { (Get-Item $zipPath).Length } else { $null }
  evidence_summary_mode = [bool]$EvidenceSummaryMode
  intentional_policy_exclusions = $policyExclusions
  denied_skipped_count = $deniedSkipped.Count
  members = @($copied)
}
$manifestJson = ($manifest | ConvertTo-Json -Depth 6)
Set-Content -Path $manifestPath -Value $manifestJson -Encoding utf8
Remove-Item -Recurse -Force $staging

[pscustomobject]@{
  ok = $true
  dry_run = [bool]$DryRun
  branch = $branch
  head = $head
  file_count = $copied.Count
  uncompressed_bytes = $uncompressed
  compressed_bytes = $manifest.compressed_bytes
  manifest_path = $manifestPath
  zip_path = if ($DryRun) { $null } else { $zipPath }
  intentional_policy_exclusions = $policyExclusions
} | ConvertTo-Json -Depth 5
