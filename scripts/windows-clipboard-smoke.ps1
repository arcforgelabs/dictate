<#
.SYNOPSIS
Checks that a dictation leaves the Windows clipboard as it was and out of Win+V history.

.DESCRIPTION
Puts text, an image, a file list and HTML on the clipboard, saves a SHA-256 of
every format, pastes one synthetic dictation through Dictate's PasteOutput,
then compares every format again. It also reads clipboard history (Win+V),
when Windows lets it, to show the dictated text never reached it.

Run it from the repository root with Windows PowerShell in STA mode:

    powershell -NoProfile -STA -ExecutionPolicy Bypass -File scripts\windows-clipboard-smoke.ps1

-Target edit (default) pastes into a hidden EDIT control by message, so it
works without keyboard focus (CI). -Target notepad opens Notepad and sends the
real Ctrl+V; use it on an unlocked desktop and close Notepad without saving.

-EnableHistoryForTest turns clipboard history on for the current user first.
It changes a user setting, so it is meant for throwaway CI machines only.

Two OLE bookkeeping formats ("DataObject", "Ole Private Data") point at the
source app's live data object; Dictate does not carry them over, so they are
left out of the comparison. The restored clipboard also carries
ExcludeClipboardContentFromMonitorProcessing, so the restore does not add the
old contents to history a second time.
#>
param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [ValidateSet("edit", "notepad")]
    [string]$Target = "edit",
    [switch]$EnableHistoryForTest
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

if ([System.Threading.Thread]::CurrentThread.GetApartmentState() -ne "STA") {
    throw "Run this script in STA mode: powershell -NoProfile -STA -File scripts\windows-clipboard-smoke.ps1"
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

public static class DictateClipDump {
    [DllImport("user32.dll", SetLastError = true)] static extern bool OpenClipboard(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool CloseClipboard();
    [DllImport("user32.dll", SetLastError = true)] static extern uint EnumClipboardFormats(uint format);
    [DllImport("user32.dll")] static extern IntPtr GetClipboardData(uint format);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClipboardFormatNameW(uint format, StringBuilder name, int size);
    [DllImport("kernel32.dll")] static extern UIntPtr GlobalSize(IntPtr handle);
    [DllImport("kernel32.dll")] static extern IntPtr GlobalLock(IntPtr handle);
    [DllImport("kernel32.dll")] static extern bool GlobalUnlock(IntPtr handle);
    [DllImport("gdi32.dll")] static extern uint GetEnhMetaFileBits(IntPtr handle, uint size, byte[] buffer);

    static bool IsHandleFormat(uint f) {
        if (f == 2 || f == 3 || f == 9 || f == 0x80 || f == 0x82 || f == 0x83 || f == 0x8E) return true;
        return f >= 0x200 && f <= 0x3FF;
    }

    public static SortedDictionary<string, string> Dump() {
        var result = new SortedDictionary<string, string>();
        bool opened = false;
        for (int i = 0; i < 100 && !(opened = OpenClipboard(IntPtr.Zero)); i++) System.Threading.Thread.Sleep(20);
        if (!opened) throw new InvalidOperationException("clipboard is held open by another app");
        try {
            using (var sha = SHA256.Create()) {
                uint f = 0;
                while ((f = EnumClipboardFormats(f)) != 0) {
                    var name = new StringBuilder(256);
                    int length = GetClipboardFormatNameW(f, name, 256);
                    string key = length > 0 ? name.ToString() : ("CF_" + f);
                    if (IsHandleFormat(f)) { result[key] = "(GDI handle, not compared)"; continue; }
                    IntPtr handle = GetClipboardData(f);
                    if (handle == IntPtr.Zero) { result[key] = "(no data)"; continue; }
                    byte[] data;
                    if (f == 14) {
                        uint size = GetEnhMetaFileBits(handle, 0, null);
                        data = new byte[size];
                        GetEnhMetaFileBits(handle, size, data);
                    } else {
                        long size = (long)GlobalSize(handle).ToUInt64();
                        IntPtr p = GlobalLock(handle);
                        if (p == IntPtr.Zero) { result[key] = "(not global memory)"; continue; }
                        try {
                            data = new byte[size];
                            Marshal.Copy(p, data, 0, (int)size);
                        } finally {
                            GlobalUnlock(handle);
                        }
                    }
                    result[key] = data.Length + " bytes sha256 " + BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "");
                }
            }
        } finally {
            CloseClipboard();
        }
        return result;
    }
}
"@

function Set-MixedClipboard {
    param([string]$FilePath)
    $data = New-Object System.Windows.Forms.DataObject
    $data.SetText("Copied before the dictation`r`nsecond line", [System.Windows.Forms.TextDataFormat]::UnicodeText)
    $bitmap = New-Object System.Drawing.Bitmap 16, 16
    for ($x = 0; $x -lt 16; $x++) {
        for ($y = 0; $y -lt 16; $y++) {
            $bitmap.SetPixel($x, $y, [System.Drawing.Color]::FromArgb(255, $x * 16, $y * 16, 128))
        }
    }
    $data.SetImage($bitmap)
    $files = New-Object System.Collections.Specialized.StringCollection
    [void]$files.Add($FilePath)
    $data.SetFileDropList($files)
    $html = "Version:0.9`r`nStartHTML:-1`r`nEndHTML:-1`r`nStartFragment:0000000000`r`nEndFragment:0000000000`r`n<b>copied</b>"
    $data.SetData([System.Windows.Forms.DataFormats]::Html, $html)
    [System.Windows.Forms.Clipboard]::SetDataObject($data, $true, 20, 100)
}

function Get-ClipboardHistoryTexts {
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $null = [Windows.ApplicationModel.DataTransfer.Clipboard, Windows.ApplicationModel.DataTransfer, ContentType = WindowsRuntime]
        $null = [Windows.ApplicationModel.DataTransfer.ClipboardHistoryItemsResult, Windows.ApplicationModel.DataTransfer, ContentType = WindowsRuntime]
        $null = [Windows.ApplicationModel.DataTransfer.StandardDataFormats, Windows.ApplicationModel.DataTransfer, ContentType = WindowsRuntime]
        if (-not [Windows.ApplicationModel.DataTransfer.Clipboard]::IsHistoryEnabled()) {
            return @{ Readable = $false; Reason = "clipboard history is turned off" }
        }
        $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } | Select-Object -First 1
        $operation = [Windows.ApplicationModel.DataTransfer.Clipboard]::GetHistoryItemsAsync()
        $task = $asTask.MakeGenericMethod([Windows.ApplicationModel.DataTransfer.ClipboardHistoryItemsResult]).Invoke($null, @($operation))
        [void]$task.Wait(10000)
        $result = $task.Result
        if ("$($result.Status)" -ne "Success") {
            return @{ Readable = $false; Reason = "history status $($result.Status)" }
        }
        $texts = @()
        foreach ($item in $result.Items) {
            $view = $item.Content
            if ($view.Contains([Windows.ApplicationModel.DataTransfer.StandardDataFormats]::Text)) {
                $textTask = $asTask.MakeGenericMethod([string]).Invoke($null, @($view.GetTextAsync()))
                [void]$textTask.Wait(5000)
                $texts += [string]$textTask.Result
            }
        }
        return @{ Readable = $true; Texts = $texts }
    } catch {
        return @{ Readable = $false; Reason = $_.Exception.Message }
    }
}

$failures = @()
$dictated = "dictate clipboard smoke " + [guid]::NewGuid().ToString("N")
$control = "dictate history control " + [guid]::NewGuid().ToString("N")
$dropFile = Join-Path $env:TEMP "dictate-clipboard-smoke.txt"
Set-Content -LiteralPath $dropFile -Value "file list entry" -Encoding ascii

if ($EnableHistoryForTest) {
    Write-Step "Turning clipboard history on for this user (test machines only)"
    New-Item -Path "HKCU:\Software\Microsoft\Clipboard" -Force | Out-Null
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Clipboard" -Name "EnableClipboardHistory" -Value 1 -Type DWord
    Start-Sleep -Seconds 2
}

Write-Step "Checking whether clipboard history can be read here"
[System.Windows.Forms.Clipboard]::SetText($control)
Start-Sleep -Seconds 2
$history = Get-ClipboardHistoryTexts
$historyWorks = $history.Readable -and ($history.Texts -contains $control)
if ($historyWorks) {
    Write-Host "    history is readable and records ordinary copies"
} elseif ($history.Readable) {
    Write-Host "    history is readable but did not record an ordinary copy; the history check is not conclusive here"
} else {
    Write-Host "    history is not readable here: $($history.Reason)"
}

Write-Step "Putting text, an image, a file list and HTML on the clipboard"
Set-MixedClipboard -FilePath $dropFile
$before = [DictateClipDump]::Dump()
foreach ($key in $before.Keys) { Write-Host ("    {0,-40} {1}" -f $key, $before[$key]) }

Write-Step "Pasting one synthetic dictation into: $Target"
$json = & $Python scripts\windows_clipboard_smoke.py --target $Target --text $dictated | Select-Object -Last 1
$pasteExit = $LASTEXITCODE
Write-Host "    $json"
if ($pasteExit -ne 0) { $failures += "paste helper exited $pasteExit" }

Start-Sleep -Milliseconds 500
$after = [DictateClipDump]::Dump()

Write-Step "Comparing every format"
$ignored = @("DataObject", "Ole Private Data")
foreach ($key in $before.Keys) {
    if ($ignored -contains $key) { Write-Host "    $key not carried over (OLE bookkeeping)"; continue }
    if (-not $after.ContainsKey($key)) {
        $failures += "format $key is missing after the dictation"
    } elseif ($after[$key] -ne $before[$key]) {
        $failures += "format $key changed: $($before[$key]) -> $($after[$key])"
    } else {
        Write-Host "    $key identical"
    }
}
foreach ($key in $after.Keys) {
    if (-not $before.ContainsKey($key)) {
        if ($key -eq "ExcludeClipboardContentFromMonitorProcessing") {
            Write-Host "    $key added (keeps the restore out of history)"
        } else {
            $failures += "format $key appeared after the dictation"
        }
    }
}

Write-Step "Checking clipboard history for the dictated text"
$historyAfter = Get-ClipboardHistoryTexts
if ($historyAfter.Readable) {
    if ($historyAfter.Texts -contains $dictated) {
        $failures += "the dictated text is in clipboard history"
    } elseif ($historyWorks) {
        Write-Host "    dictated text is not in history ($($historyAfter.Texts.Count) text items read)"
    } else {
        Write-Host "    dictated text is not in history, but history did not record the control copy either, so this proves little"
    }
} else {
    Write-Host "    history not readable: $($historyAfter.Reason)"
}

Remove-Item -LiteralPath $dropFile -ErrorAction SilentlyContinue

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Host "FAIL: $_" }
    exit 1
}
Write-Host "PASS: the clipboard is byte-identical apart from the history marker"
