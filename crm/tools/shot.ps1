# Screenshot of the web build with headless Microsoft Edge (comes with Windows 11).
#   powershell -File crm/tools/shot.ps1 -Url "http://127.0.0.1:28380/contacts?theme=light" -Out .lead/crm/shots/contacts.png
#   -Width 390 -Height 844 for a phone, -Height 1800 for a long page.
# A fresh browser profile each time, so the demo data is new and the welcome screen is skipped
# whenever the URL carries ?theme= or ?lang= .
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
$edgeArgs = "--headless=new --disable-gpu --hide-scrollbars --no-first-run --no-default-browser-check " +
  "--user-data-dir=`"$profileDir`" --window-size=$Width,$Height --virtual-time-budget=$Wait " +
  "--screenshot=`"$full`" `"$Url`""
$p = Start-Process -FilePath $edge -ArgumentList $edgeArgs -PassThru -WindowStyle Hidden
if (-not $p.WaitForExit(60000)) { try { $p.Kill() } catch {} }
Start-Sleep -Milliseconds 300
Remove-Item -Recurse -Force $profileDir -ErrorAction SilentlyContinue
if (Test-Path $full) { "saved $full" } else { "FAILED: no screenshot" }
