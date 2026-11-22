# Captures the main window of a running process to a PNG (PrintWindow: only that window,
# even if covered, nothing else from the desktop).
#   powershell -File crm/tools/capture-window.ps1 -ProcessId 1234 -Out shot.png
param(
  [Parameter(Mandatory = $true)][int]$ProcessId,
  [Parameter(Mandatory = $true)][string]$Out
)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class Win {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[Win]::SetProcessDPIAware() | Out-Null
$p = Get-Process -Id $ProcessId -ErrorAction Stop
$p.Refresh()
$h = $p.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { "NO WINDOW"; exit 1 }
$r = New-Object Win+RECT
[Win]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $hgt = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $hgt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[Win]::PrintWindow($h, $hdc, 2) | Out-Null
$g.ReleaseHdc($hdc); $g.Dispose()
$full = [System.IO.Path]::GetFullPath($Out)
New-Item -ItemType Directory -Force (Split-Path $full) | Out-Null
$bmp.Save($full, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
"saved $full ($w x $hgt)"
