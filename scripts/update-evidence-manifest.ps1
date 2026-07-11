[CmdletBinding()]
param(
    [string]$EvidenceRoot = (Join-Path $PSScriptRoot '..\evidence'),
    [string]$OutputPath = (Join-Path $PSScriptRoot '..\evidence\manifest.csv')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Drawing

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$rows = Get-ChildItem -LiteralPath $EvidenceRoot -Recurse -File |
    Where-Object Extension -In @('.png', '.ppm') |
    Sort-Object FullName |
    ForEach-Object {
        $image = [System.Drawing.Image]::FromFile($_.FullName)
        try {
            [PSCustomObject]@{
                path = $_.FullName.Substring($repositoryRoot.Length + 1).Replace('\', '/')
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                width = $image.Width
                height = $image.Height
                bytes = $_.Length
                modified = $_.LastWriteTime.ToString('o')
            }
        }
        finally {
            $image.Dispose()
        }
    }

$rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8
Write-Output "Wrote $($rows.Count) image records to $OutputPath"

