# Runs inside the interactive console session (scheduled task, Interactive logon).
# Launches the installed Dictate desktop app and records, relative to the shell
# start: the engine handshake (ui-server.json write time), the WebView2
# connections to the engine port (their CreationTime), and model ready (first
# /api/state with modelReady, polled with a non-blocking HttpClient). Screenshots
# the main window every 0.5 s and clicks the mic once about 1.3 s after the
# window appears.
param([Parameter(Mandatory)] [string]$ShellExe, [string]$Out = "C:\ready-proof\out")
$ErrorActionPreference = "Continue"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Start-Transcript -Path (Join-Path $Out "session-transcript.txt") | Out-Null
Add-Type -AssemblyName System.Drawing, System.Net.Http, System.Windows.Forms
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public static class W {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool repaint);
  public static IntPtr Find(uint pid, string title) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (p != pid || !IsWindowVisible(h)) return true;
      var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
      if (sb.ToString() == title) { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@
[void][W]::SetProcessDPIAware()

$events = New-Object System.Collections.ArrayList
$script:startTicks = 0L
function Rel([long]$Ticks) { [int](($Ticks - $script:startTicks) / 10000) }
function Mark([string]$Name, $Detail = $null, [long]$Ticks = 0) {
    if ($Ticks -eq 0) { $Ticks = [DateTime]::UtcNow.Ticks }
    [void]$events.Add([pscustomobject]@{ ms = (Rel $Ticks); event = $Name; detail = $Detail })
    Write-Host ("{0,6} ms  {1} {2}" -f (Rel $Ticks), $Name, $Detail)
}
function Shot([IntPtr]$Hwnd, [string]$Name) {
    $r = New-Object W+RECT
    if (-not [W]::GetWindowRect($Hwnd, [ref]$r)) { return }
    $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
    if ($w -le 0 -or $h -le 0) { return }
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.Left, $r.Top, 0, 0, (New-Object System.Drawing.Size $w, $h))
    $g.Dispose()
    $bmp.Save((Join-Path $Out "$Name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
}

$handshakePath = Join-Path $env:LOCALAPPDATA "dictate\ui-server.json"
Get-Process -Name "dictate*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Remove-Item -Force -ErrorAction SilentlyContinue $handshakePath
$http = New-Object System.Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromSeconds(60)
# Warm up the slow first calls (CIM provider, process list, window enumeration)
# so they are not on the clock.
$warm = [Diagnostics.Stopwatch]::StartNew()
$null = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
$null = Get-Process -Name msedgewebview2 -ErrorAction SilentlyContinue
$null = [W]::Find([uint32]$PID, "none")
Write-Host "warm-up took $($warm.ElapsedMilliseconds) ms"

$script:startTicks = [DateTime]::UtcNow.Ticks
$proc = Start-Process -FilePath $ShellExe -PassThru
Mark "shell started" "pid $($proc.Id)"

$hwnd = [IntPtr]::Zero; $windowTicks = 0L; $next = 0; $loadingShot = $false; $clicked = $false
$hs = $null; $stateTask = $null; $stateNotBefore = 0; $readyTicks = 0L; $firstState = $null
$conns = @{}; $nextConnPoll = 0; $lastWrite = 0L
$deadlineTicks = $script:startTicks + 120 * 10000000L
while ([DateTime]::UtcNow.Ticks -lt $deadlineTicks) {
    $now = Rel ([DateTime]::UtcNow.Ticks)
    $fi = [IO.FileInfo]$handshakePath
    if ($fi.Exists) {
        $wt = $fi.LastWriteTimeUtc.Ticks
        if ($wt -ne $lastWrite) {
            $lastWrite = $wt
            try {
                $c = [IO.File]::ReadAllText($handshakePath) | ConvertFrom-Json
                Mark "handshake written (ui-server.json LastWriteTime)" $c.url $wt
                if (-not $hs -and $c.url -and $c.token) {
                    $hs = $c
                    $http.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", $c.token)
                }
            } catch { $lastWrite = 0L }
        }
    } elseif ($lastWrite) { Mark "handshake file removed"; $lastWrite = 0L }
    if ($hs -and -not $readyTicks) {
        if ($stateTask -and $stateTask.IsCompleted) {
            $doneTicks = [DateTime]::UtcNow.Ticks
            if ($stateTask.Status -eq "RanToCompletion") {
                $s = $stateTask.Result | ConvertFrom-Json
                if (-not $firstState) { $firstState = $true; Mark "first /api/state answered" "modelReady=$($s.modelReady) phase=$($s.modelLoad.phase)" $doneTicks }
                if ($s.modelReady) { $readyTicks = $doneTicks; Mark "model ready (first /api/state with modelReady=true)" $null $doneTicks }
            }
            $stateTask = $null; $stateNotBefore = $now + 200
        }
        if (-not $stateTask -and -not $readyTicks -and $now -ge $stateNotBefore) { $stateTask = $http.GetStringAsync("$($hs.url)/api/state") }
    }
    if ($hs -and $now -ge $nextConnPoll) {
        $port = ([Uri]$hs.url).Port
        $webview = @(Get-Process -Name msedgewebview2 -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
        foreach ($t in @(Get-NetTCPConnection -RemotePort $port -ErrorAction SilentlyContinue | Where-Object { $webview -contains $_.OwningProcess })) {
            $key = "$($t.LocalPort)"
            if (-not $conns.ContainsKey($key)) { $conns[$key] = $t.CreationTime.ToUniversalTime().Ticks }
        }
        $nextConnPoll = $now + 700
    }
    if ($hwnd -eq [IntPtr]::Zero) {
        $hwnd = [W]::Find([uint32]$proc.Id, "Dictate")
        if ($hwnd -ne [IntPtr]::Zero) {
            $windowTicks = [DateTime]::UtcNow.Ticks; Mark "main window shown"
            # The 1100x768 window is taller than the VM's 1024x768 screen; fit it to
            # the work area so toasts at its bottom are not under the taskbar.
            $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
            [void][W]::MoveWindow($hwnd, $wa.Left, $wa.Top, $wa.Width, $wa.Height, $true)
            [void][W]::SetForegroundWindow($hwnd)
        }
    }
    if ($hwnd -ne [IntPtr]::Zero) {
        $sinceWindow = $now - (Rel $windowTicks)
        if ($now -ge $next) { Shot $hwnd ("t{0:D6}" -f $now); $next = $now + 500 }
        if (-not $loadingShot -and $sinceWindow -ge 1000) { Shot $hwnd "loading-1s"; $loadingShot = $true; Mark "screenshot loading-1s" }
        if ($loadingShot -and -not $clicked -and $sinceWindow -ge 1300) {
            $clicked = $true
            $r = New-Object W+RECT; [void][W]::GetWindowRect($hwnd, [ref]$r)
            # Find the mic cradle in the loading screenshot: on the window's centre
            # column, the first run of >= 80 px that differs from the background.
            $bmp = New-Object System.Drawing.Bitmap (Join-Path $Out "loading-1s.png")
            $bg = $bmp.GetPixel(30, 200)
            $cx = [int]($bmp.Width / 2); $runStart = -1; $gap = 0; $found = $null
            for ($py = 80; $py -lt $bmp.Height - 80 -and -not $found; $py++) {
                $p = $bmp.GetPixel($cx, $py)
                $diff = [Math]::Abs($p.R - $bg.R) + [Math]::Abs($p.G - $bg.G) + [Math]::Abs($p.B - $bg.B)
                if ($diff -gt 12) { if ($runStart -lt 0) { $runStart = $py }; $gap = 0 }
                elseif ($runStart -ge 0) {
                    $gap++
                    if ($gap -gt 3) { if (($py - $gap - $runStart) -ge 80) { $found = [int](($runStart + $py - $gap) / 2) } else { $runStart = -1 }; $gap = 0 }
                }
            }
            $bmp.Dispose()
            if ($found) { $x = $r.Left + $cx; $y = $r.Top + $found } else { $x = $r.Left + $cx; $y = $r.Top + 354 }
            [void][W]::SetForegroundWindow($hwnd)
            [void][W]::SetCursorPos($x, $y)
            [W]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero); [W]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
            Mark "mic clicked" "screen $x,$y (cradle found in screenshot: $([bool]$found))"
            Start-Sleep -Milliseconds 350
            Shot $hwnd "mic-click"
            Mark "screenshot mic-click"
        }
        if ($readyTicks -and (Rel ([DateTime]::UtcNow.Ticks)) -ge (Rel $readyTicks) + 1500) {
            [void][W]::SetCursorPos(5, 5)
            Start-Sleep -Milliseconds 200
            Shot $hwnd "ready"
            Mark "screenshot ready"
            break
        }
    }
    $took = (Rel ([DateTime]::UtcNow.Ticks)) - $now
    if ($took -gt 600) { Mark "slow probe loop iteration" "$took ms" }
    Start-Sleep -Milliseconds 40
}
foreach ($k in $conns.Keys) { Mark "WebView2 connection to engine port created" "local port $k" $conns[$k] }
$events | Sort-Object ms | ConvertTo-Json | Set-Content -Path (Join-Path $Out "events.json") -Encoding UTF8
Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "dictate") -Recurse -Filter "*.log" -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $Out ("log-" + $_.Name)) }
Stop-Transcript | Out-Null
Set-Content -Path (Join-Path $Out "done.txt") -Value "done"
