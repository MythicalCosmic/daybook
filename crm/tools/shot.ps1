# Screenshot of the web build with headless Microsoft Edge (comes with Windows 11).
#   powershell -File crm/tools/shot.ps1 -Url "http://127.0.0.1:28380/contacts?theme=light" -Out .lead/crm/shots/contacts.png
#   -Width 390 -Height 844 for a phone, -Height 1800 for a long page.
# A fresh browser profile each time, so the demo data is new and the welcome screen is skipped
# whenever the URL carries ?theme= or ?lang= .
# Edge won't open a window narrower than ~500 px, so phone widths are shot through an iframe of
# exactly that width (a true phone viewport) and the picture is cropped to it.
param(
  [Parameter(Mandatory = $true)][string]$Url,
  [Parameter(Mandatory = $true)][string]$Out,
  [int]$Width = 1440,
  [int]$Height = 900,
  [int]$Wait = 12000
)
$edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { $edge = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe" }
$full = [System.IO.Path]::GetFullPath($Out)
New-Item -ItemType Directory -Force (Split-Path $full) | Out-Null
if (Test-Path $full) { Remove-Item -Force $full }
$profileDir = Join-Path $env:TEMP ("crm-shot-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $profileDir | Out-Null

$target = $Url
$winW = $Width
$narrow = $Width -lt 520
if ($narrow) {
  $winW = 600
  $frame = Join-Path $profileDir "frame.html"
  $safe = $Url.Replace('&', '&amp;').Replace('"', '&quot;')
  "<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;background:#000;overflow:hidden}iframe{border:0;display:block}</style></head><body><iframe src=`"$safe`" width=`"$Width`" height=`"$Height`"></iframe></body></html>" |
    Out-File -Encoding utf8 $frame
  $target = ([System.Uri]$frame).AbsoluteUri
}

$edgeArgs = "--headless=new --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check " +
  "--allow-file-access-from-files --user-data-dir=`"$profileDir`" --window-size=$winW,$Height --virtual-time-budget=$Wait " +
  "--screenshot=`"$full`" `"$target`""
$p = Start-Process -FilePath $edge -ArgumentList $edgeArgs -PassThru -WindowStyle Hidden
if (-not $p.WaitForExit(60000)) { try { $p.Kill() } catch {} }
Start-Sleep -Milliseconds 300

if ($narrow -and (Test-Path $full)) {
  Add-Type -AssemblyName System.Drawing
  $img = [System.Drawing.Image]::FromFile($full)
  $crop = New-Object System.Drawing.Bitmap $Width, ([math]::Min($Height, $img.Height))
  $g = [System.Drawing.Graphics]::FromImage($crop)
  $g.DrawImage($img, (New-Object System.Drawing.Rectangle 0, 0, $crop.Width, $crop.Height), (New-Object System.Drawing.Rectangle 0, 0, $crop.Width, $crop.Height), [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose(); $img.Dispose()
  $crop.Save($full, [System.Drawing.Imaging.ImageFormat]::Png); $crop.Dispose()
}
Remove-Item -Recurse -Force $profileDir -ErrorAction SilentlyContinue
if (Test-Path $full) { "saved $full" } else { "FAILED: no screenshot" }
