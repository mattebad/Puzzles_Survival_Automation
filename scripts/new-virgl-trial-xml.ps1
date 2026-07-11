[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BaselineXml,
    [Parameter(Mandatory = $true)][string]$OutputXml,
    [string]$RenderNode = '/dev/dri/by-path/pci-0000:00:02.0-render'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$raw = Get-Content -LiteralPath $BaselineXml -Raw
$domainStart = $raw.IndexOf('<domain')
if ($domainStart -lt 0) {
    throw 'No <domain> root element found in baseline input.'
}

[xml]$document = $raw.Substring($domainStart)
$devices = $document.domain.devices
$vnc = @($devices.graphics | Where-Object type -eq 'vnc')
$existingEgl = @($devices.graphics | Where-Object type -eq 'egl-headless')
$video = @($devices.video)

if ($vnc.Count -ne 1 -or $existingEgl.Count -ne 0 -or $video.Count -ne 1) {
    throw 'Expected exactly one VNC device, no existing egl-headless device, and one video device.'
}
if ($video[0].model.type -ne 'qxl') {
    throw "Expected QXL baseline, found '$($video[0].model.type)'."
}

$egl = $document.CreateElement('graphics')
$egl.SetAttribute('type', 'egl-headless')
$gl = $document.CreateElement('gl')
$gl.SetAttribute('rendernode', $RenderNode)
[void]$egl.AppendChild($gl)
[void]$devices.InsertAfter($egl, $vnc[0])

$model = $video[0].model
foreach ($attribute in @('ram', 'vram', 'vgamem')) {
    [void]$model.RemoveAttribute($attribute)
}
$model.SetAttribute('type', 'virtio')
$model.SetAttribute('heads', '1')
$model.SetAttribute('primary', 'yes')
$acceleration = $document.CreateElement('acceleration')
$acceleration.SetAttribute('accel3d', 'yes')
[void]$model.AppendChild($acceleration)

# Match the ordering emitted by this host's Unraid VM manager:
# VNC graphics, egl-headless graphics, video, then audio.
$audio = @($devices.audio)
if ($audio.Count -ne 1) {
    throw 'Expected exactly one audio device in the baseline.'
}
[void]$devices.RemoveChild($video[0])
[void]$devices.InsertBefore($video[0], $audio[0])

$settings = [System.Xml.XmlWriterSettings]::new()
$settings.Indent = $true
$settings.Encoding = [System.Text.UTF8Encoding]::new($false)
$settings.NewLineChars = "`n"
$settings.NewLineHandling = 'Replace'
$writer = [System.Xml.XmlWriter]::Create($OutputXml, $settings)
try {
    $document.Save($writer)
}
finally {
    $writer.Dispose()
}

[PSCustomObject]@{
    output_xml = (Resolve-Path $OutputXml).Path
    sha256 = (Get-FileHash -LiteralPath $OutputXml -Algorithm SHA256).Hash.ToLowerInvariant()
    render_node = $RenderNode
    mutation = 'QXL -> VirtIO 3D plus egl-headless; all other domain elements preserved'
}
