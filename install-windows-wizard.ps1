param(
    [string]$InitialAction = "Install"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$TermsUrl = "https://arcforge.au/terms"
$DocumentationUrl = "https://github.com/arcforgelabs/dictate#readme"
$HostedWindowsUpdateUrl = "https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/update.ps1"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function New-ActionRadio {
    param(
        [string]$Text,
        [string]$Tag,
        [int]$Top,
        [bool]$Checked = $false
    )
    $radio = New-Object System.Windows.Forms.RadioButton
    $radio.Text = $Text
    $radio.Tag = $Tag
    $radio.Left = 18
    $radio.Top = $Top
    $radio.Width = 430
    $radio.Checked = $Checked
    return $radio
}

function Get-SelectedAction {
    foreach ($control in $actionsGroup.Controls) {
        if ($control.Checked) {
            return [string]$control.Tag
        }
    }
    return "Install"
}

function Append-Log {
    param([string]$Message)
    $logBox.AppendText($Message + [Environment]::NewLine)
    $logBox.SelectionStart = $logBox.TextLength
    $logBox.ScrollToCaret()
}

function Open-ExternalUrl {
    param([string]$Url)
    Start-Process $Url
}

function Sync-RunButton {
    if ($null -ne $runButton) {
        $runButton.Enabled = $termsCheck.Checked
    }
}

function Sync-ShortcutOptions {
    if ($null -ne $startupCheck) {
        if ($shortcutCheck.Checked) {
            $startupCheck.Enabled = $true
        } else {
            $startupCheck.Checked = $false
            $startupCheck.Enabled = $false
        }
    }
}

function Get-StartMenuProgramsDir {
    $programsDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    if (-not $env:APPDATA) {
        $programsDir = Join-Path $HOME "AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
    }
    return $programsDir
}

function Get-StartupShortcutPath {
    return (Join-Path (Join-Path (Get-StartMenuProgramsDir) "Startup") "Dictate.lnk")
}

function Drain-LogQueue {
    param($Queue)
    $line = $null
    while ($Queue.TryDequeue([ref]$line)) {
        Append-Log $line
        $line = $null
    }
}

function Invoke-LoggedProcess {
    param(
        [string]$Label,
        [string]$FileName,
        [string]$ArgumentString,
        [string]$WorkingDirectory = $PSScriptRoot
    )

    Append-Log "==> $Label"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = $ArgumentString
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $stdoutQueue = New-Object "System.Collections.Concurrent.ConcurrentQueue[string]"
    $stderrQueue = New-Object "System.Collections.Concurrent.ConcurrentQueue[string]"
    $stdoutHandler = [System.Diagnostics.DataReceivedEventHandler]{
        param($sender, $eventArgs)
        if ($null -ne $eventArgs.Data) {
            $stdoutQueue.Enqueue($eventArgs.Data)
        }
    }
    $stderrHandler = [System.Diagnostics.DataReceivedEventHandler]{
        param($sender, $eventArgs)
        if ($null -ne $eventArgs.Data) {
            $stderrQueue.Enqueue($eventArgs.Data)
        }
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    $process.add_OutputDataReceived($stdoutHandler)
    $process.add_ErrorDataReceived($stderrHandler)
    try {
        [void]$process.Start()
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        while (-not $process.WaitForExit(100)) {
            Drain-LogQueue $stdoutQueue
            Drain-LogQueue $stderrQueue
            [System.Windows.Forms.Application]::DoEvents()
        }
        $process.WaitForExit()
        Drain-LogQueue $stdoutQueue
        Drain-LogQueue $stderrQueue
        if ($process.ExitCode -ne 0) {
            throw "$Label failed with exit code $($process.ExitCode)."
        }
    } finally {
        $process.remove_OutputDataReceived($stdoutHandler)
        $process.remove_ErrorDataReceived($stderrHandler)
        $process.Dispose()
    }
}

function Invoke-Step {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $PSScriptRoot
    )

    $argumentString = (
        @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$FilePath`"") + $Arguments
    ) -join " "
    Invoke-LoggedProcess -Label $Label -FileName "powershell" -ArgumentString $argumentString -WorkingDirectory $WorkingDirectory
}

function Invoke-DictateUpdate {
    param([string[]]$Arguments)

    if (Test-Path (Join-Path $PSScriptRoot ".git")) {
        Invoke-Step "Updating Dictate" (Join-Path $PSScriptRoot "update-windows.ps1") $Arguments
        return
    }

    $tempUpdater = Join-Path ([System.IO.Path]::GetTempPath()) ("dictate-update-" + [guid]::NewGuid().ToString("N") + ".ps1")
    try {
        Append-Log "==> Fetching current hosted updater"
        Invoke-WebRequest -UseBasicParsing -Uri $HostedWindowsUpdateUrl -OutFile $tempUpdater
        $workingDirectory = Split-Path -Parent $PSScriptRoot
        Invoke-Step -Label "Updating Dictate from hosted source" -FilePath $tempUpdater -Arguments $Arguments -WorkingDirectory $workingDirectory
    } finally {
        Remove-Item -Force -ErrorAction SilentlyContinue -Path $tempUpdater
    }
}

function Invoke-DictateDoctorFix {
    $dictateExe = Join-Path $PSScriptRoot ".venv\Scripts\dictate.exe"
    if (-not (Test-Path $dictateExe)) {
        throw "Dictate is not installed in this source folder. Run Install first."
    }

    Invoke-LoggedProcess "Repairing Dictate with doctor --fix" $dictateExe "doctor --quick --fix --type-backend pynput"
}

function Start-SelectedAction {
    $runButton.Enabled = $false
    $closeButton.Enabled = $false
    $logBox.Clear()
    try {
        if (-not $termsCheck.Checked) {
            throw "Please acknowledge the Dictate terms before continuing."
        }
        $action = Get-SelectedAction
        $commonArgs = @()
        if (-not $verifyCheck.Checked) { $commonArgs += "-NoVerify" }
        if (-not $prepareCheck.Checked) { $commonArgs += "-NoPrepareTurbo" }
        if (-not $shortcutCheck.Checked) { $commonArgs += "-NoShortcut" }
        if (-not $startupCheck.Checked) { $commonArgs += "-NoStartup" }

        if ($action -eq "Install") {
            Invoke-Step "Installing Dictate" (Join-Path $PSScriptRoot "install-windows.ps1") $commonArgs
        } elseif ($action -eq "Update") {
            $updateArgs = @($commonArgs)
            if ($startupCheck.Checked) { $updateArgs += "-ForceStartup" }
            Invoke-DictateUpdate $updateArgs
        } elseif ($action -eq "Repair") {
            Invoke-DictateDoctorFix
        } elseif ($action -eq "Uninstall") {
            $uninstallArgs = @()
            if ($removeUserDataCheck.Checked) { $uninstallArgs += "-RemoveUserData" }
            Invoke-Step "Uninstalling Dictate" (Join-Path $PSScriptRoot "uninstall-windows.ps1") $uninstallArgs
        }
        Append-Log ""
        Append-Log "Done."
        [System.Windows.Forms.MessageBox]::Show(
            "Dictate $($action.ToLowerInvariant()) completed.",
            "Dictate Setup",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    } catch {
        Append-Log ""
        Append-Log "ERROR: $($_.Exception.Message)"
        [System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            "Dictate Setup",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } finally {
        Sync-RunButton
        $closeButton.Enabled = $true
    }
}

$paper = [System.Drawing.Color]::FromArgb(239, 236, 230)
$surface = [System.Drawing.Color]::FromArgb(255, 255, 255)
$surface2 = [System.Drawing.Color]::FromArgb(247, 245, 241)
$surface3 = [System.Drawing.Color]::FromArgb(240, 237, 231)
$ink = [System.Drawing.Color]::FromArgb(27, 26, 22)
$muted = [System.Drawing.Color]::FromArgb(105, 101, 91)
$subtle = [System.Drawing.Color]::FromArgb(145, 139, 126)
$hairline = [System.Drawing.Color]::FromArgb(232, 228, 220)
$live = [System.Drawing.Color]::FromArgb(47, 143, 99)
$danger = [System.Drawing.Color]::FromArgb(197, 64, 44)

function New-UiFont {
    param([float]$Size, [System.Drawing.FontStyle]$Style = [System.Drawing.FontStyle]::Regular)
    return New-Object System.Drawing.Font("Segoe UI Variable Text", $Size, $Style)
}

function New-Panel {
    param([int]$Left, [int]$Top, [int]$Width, [int]$Height, [System.Drawing.Color]$BackColor = $surface)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Left = $Left
    $panel.Top = $Top
    $panel.Width = $Width
    $panel.Height = $Height
    $panel.BackColor = $BackColor
    return $panel
}

function New-Label {
    param(
        [string]$Text,
        [int]$Left,
        [int]$Top,
        [int]$Width,
        [int]$Height,
        [float]$Size = 9,
        [System.Drawing.FontStyle]$Style = [System.Drawing.FontStyle]::Regular,
        [System.Drawing.Color]$Color = $ink
    )
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Left = $Left
    $label.Top = $Top
    $label.Width = $Width
    $label.Height = $Height
    $label.Font = New-UiFont $Size $Style
    $label.ForeColor = $Color
    $label.BackColor = [System.Drawing.Color]::Transparent
    return $label
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Dictate Setup"
$form.StartPosition = "CenterScreen"
$form.ClientSize = New-Object System.Drawing.Size(476, 596)
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.BackColor = $paper
$form.Font = New-UiFont 9

$window = New-Panel 18 18 440 560 $surface
$window.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$form.Controls.Add($window)

$titleBar = New-Panel 0 0 440 40 $surface2
$window.Controls.Add($titleBar)

$mark = New-Label "A" 14 10 18 18 9 ([System.Drawing.FontStyle]::Bold) $ink
$mark.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$titleBar.Controls.Add($mark)

$chromeTitle = New-Label "Dictate" 40 9 62 18 9 ([System.Drawing.FontStyle]::Bold) $ink
$titleBar.Controls.Add($chromeTitle)
$chromeMeta = New-Label "Setup" 102 10 80 18 8.5 ([System.Drawing.FontStyle]::Regular) $subtle
$titleBar.Controls.Add($chromeMeta)

$minButton = New-Object System.Windows.Forms.Button
$minButton.Text = "-"
$minButton.Left = 344
$minButton.Top = 7
$minButton.Width = 28
$minButton.Height = 24
$minButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$minButton.FlatAppearance.BorderSize = 0
$minButton.BackColor = $surface2
$minButton.ForeColor = $muted
$minButton.Add_Click({ $form.WindowState = [System.Windows.Forms.FormWindowState]::Minimized })
$titleBar.Controls.Add($minButton)

$closeChromeButton = New-Object System.Windows.Forms.Button
$closeChromeButton.Text = "x"
$closeChromeButton.Left = 402
$closeChromeButton.Top = 7
$closeChromeButton.Width = 28
$closeChromeButton.Height = 24
$closeChromeButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$closeChromeButton.FlatAppearance.BorderSize = 0
$closeChromeButton.BackColor = $surface2
$closeChromeButton.ForeColor = $muted
$closeChromeButton.Add_Click({ $form.Close() })
$titleBar.Controls.Add($closeChromeButton)

$hero = New-Panel 0 40 440 128 $surface
$window.Controls.Add($hero)

$orb = New-Panel 28 32 58 58 $surface2
$orb.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$hero.Controls.Add($orb)
$orbIcon = New-Label "D" 0 13 56 30 18 ([System.Drawing.FontStyle]::Bold) $ink
$orbIcon.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$orb.Controls.Add($orbIcon)

$eyebrow = New-Label "SETUP" 108 27 80 18 7.5 ([System.Drawing.FontStyle]::Bold) $subtle
$hero.Controls.Add($eyebrow)
$title = New-Label "Dictate" 108 48 250 30 17 ([System.Drawing.FontStyle]::Bold) $ink
$hero.Controls.Add($title)
$subtitle = New-Label "Type as fast as you can speak." 108 82 270 24 10 ([System.Drawing.FontStyle]::Regular) $muted
$hero.Controls.Add($subtitle)

$trust = New-Panel 24 168 392 34 $surface
$trust.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$window.Controls.Add($trust)
$trust.Controls.Add((New-Label "Arc Forge" 0 8 72 18 8.5 ([System.Drawing.FontStyle]::Bold) $ink))
$trust.Controls.Add((New-Label "- Verified publisher" 75 8 130 18 8.5 ([System.Drawing.FontStyle]::Regular) $muted))
$trust.Controls.Add((New-Label "local-first" 318 8 74 18 8 ([System.Drawing.FontStyle]::Regular) $subtle))

$actionsGroup = New-Panel 24 212 392 82 $surface2
$actionsGroup.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$window.Controls.Add($actionsGroup)

$actionsLabel = New-Label "Action" 14 9 80 18 8 ([System.Drawing.FontStyle]::Bold) $subtle
$actionsGroup.Controls.Add($actionsLabel)

$actionsGroup.Controls.Add((New-ActionRadio "Install Dictate" "Install" 30 ($InitialAction -eq "Install")))
$actionsGroup.Controls.Add((New-ActionRadio "Update Dictate" "Update" 30 ($InitialAction -eq "Update")))
$actionsGroup.Controls[1].Left = 14
$actionsGroup.Controls[1].Width = 160
$actionsGroup.Controls[2].Left = 204
$actionsGroup.Controls[2].Width = 160
$actionsGroup.Controls.Add((New-ActionRadio "Repair launchers and runtime checks (doctor --fix)" "Repair" 54 ($InitialAction -eq "Repair")))
$actionsGroup.Controls.Add((New-ActionRadio "Uninstall Dictate" "Uninstall" 54 ($InitialAction -eq "Uninstall")))
$actionsGroup.Controls[3].Left = 14
$actionsGroup.Controls[3].Width = 320
$actionsGroup.Controls[4].Left = 204
$actionsGroup.Controls[4].Width = 160
foreach ($control in $actionsGroup.Controls) {
    if ($control -is [System.Windows.Forms.RadioButton]) {
        $control.BackColor = $surface2
        $control.ForeColor = $ink
        $control.Font = New-UiFont 8.5
    }
}

$optionsGroup = New-Panel 24 306 392 122 $surface2
$optionsGroup.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$window.Controls.Add($optionsGroup)

$optionsGroup.Controls.Add((New-Label "Advanced setup" 14 10 120 18 8 ([System.Drawing.FontStyle]::Bold) $subtle))

$startupCheck = New-Object System.Windows.Forms.CheckBox
$startupCheck.Text = "Launch on startup"
$startupCheck.Left = 14
$startupCheck.Top = 34
$startupCheck.Width = 170
$startupCheck.Checked = $true
$startupCheck.BackColor = $surface2
$startupCheck.ForeColor = $ink
$startupCheck.Font = New-UiFont 8.5
$optionsGroup.Controls.Add($startupCheck)
if ($InitialAction -eq "Update") {
    $startupCheck.Checked = Test-Path (Get-StartupShortcutPath)
}

$shortcutCheck = New-Object System.Windows.Forms.CheckBox
$shortcutCheck.Text = "Create Start Menu entry"
$shortcutCheck.Left = 204
$shortcutCheck.Top = 34
$shortcutCheck.Width = 180
$shortcutCheck.Checked = $true
$shortcutCheck.BackColor = $surface2
$shortcutCheck.ForeColor = $ink
$shortcutCheck.Font = New-UiFont 8.5
$shortcutCheck.Add_CheckedChanged({ Sync-ShortcutOptions })
$optionsGroup.Controls.Add($shortcutCheck)

$prepareCheck = New-Object System.Windows.Forms.CheckBox
$prepareCheck.Text = "Prepare default local model"
$prepareCheck.Left = 14
$prepareCheck.Top = 61
$prepareCheck.Width = 190
$prepareCheck.Checked = $true
$prepareCheck.BackColor = $surface2
$prepareCheck.ForeColor = $ink
$prepareCheck.Font = New-UiFont 8.5
$optionsGroup.Controls.Add($prepareCheck)

$verifyCheck = New-Object System.Windows.Forms.CheckBox
$verifyCheck.Text = "Run verification"
$verifyCheck.Left = 204
$verifyCheck.Top = 61
$verifyCheck.Width = 150
$verifyCheck.Checked = $true
$verifyCheck.BackColor = $surface2
$verifyCheck.ForeColor = $ink
$verifyCheck.Font = New-UiFont 8.5
$optionsGroup.Controls.Add($verifyCheck)

$removeUserDataCheck = New-Object System.Windows.Forms.CheckBox
$removeUserDataCheck.Text = "Also remove user config, logs, history, and models"
$removeUserDataCheck.Left = 14
$removeUserDataCheck.Top = 88
$removeUserDataCheck.Width = 360
$removeUserDataCheck.Checked = $false
$removeUserDataCheck.BackColor = $surface2
$removeUserDataCheck.ForeColor = $ink
$removeUserDataCheck.Font = New-UiFont 8.5
$optionsGroup.Controls.Add($removeUserDataCheck)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Left = 24
$logBox.Top = 438
$logBox.Width = 392
$logBox.Height = 62
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$logBox.BackColor = $surface3
$logBox.ForeColor = $muted
$logBox.Font = New-Object System.Drawing.Font("Consolas", 8)
$window.Controls.Add($logBox)

$footer = New-Panel 0 500 440 60 $surface2
$footer.Top = 500
$footer.Height = 60
$window.Controls.Add($footer)
$footer.SendToBack()

$termsCheck = New-Object System.Windows.Forms.CheckBox
$termsCheck.Text = "I understand Dictate has real-world risks and agree to the Arc Forge terms"
$termsCheck.Left = 24
$termsCheck.Top = 506
$termsCheck.Width = 322
$termsCheck.Checked = $false
$termsCheck.BackColor = $surface
$termsCheck.ForeColor = $muted
$termsCheck.Font = New-UiFont 7.8
$termsCheck.Add_CheckedChanged({ Sync-RunButton })
$window.Controls.Add($termsCheck)

$expectationLabel = New-Label "Support and maintenance are best-effort. Check important output and report issues." 42 526 330 16 7.5 ([System.Drawing.FontStyle]::Regular) $subtle
$window.Controls.Add($expectationLabel)

$termsLink = New-Object System.Windows.Forms.LinkLabel
$termsLink.Text = "Terms"
$termsLink.Left = 350
$termsLink.Top = 506
$termsLink.Width = 42
$termsLink.LinkColor = $muted
$termsLink.ActiveLinkColor = $ink
$termsLink.Font = New-UiFont 7.8
$termsLink.Add_Click({ Open-ExternalUrl $TermsUrl })
$window.Controls.Add($termsLink)

$docsLink = New-Object System.Windows.Forms.LinkLabel
$docsLink.Text = "Docs"
$docsLink.Left = 350
$docsLink.Top = 526
$docsLink.Width = 42
$docsLink.LinkColor = $muted
$docsLink.ActiveLinkColor = $ink
$docsLink.Font = New-UiFont 7.8
$docsLink.Add_Click({ Open-ExternalUrl $DocumentationUrl })
$window.Controls.Add($docsLink)

$runButton = New-Object System.Windows.Forms.Button
$runButton.Text = "Install"
$runButton.Left = 304
$runButton.Top = 526
$runButton.Width = 92
$runButton.Height = 30
$runButton.Enabled = $false
$runButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$runButton.FlatAppearance.BorderSize = 0
$runButton.BackColor = $ink
$runButton.ForeColor = $surface
$runButton.Font = New-UiFont 8.5 ([System.Drawing.FontStyle]::Bold)
$runButton.Add_Click({ Start-SelectedAction })
$window.Controls.Add($runButton)

$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text = "Close"
$closeButton.Left = 218
$closeButton.Top = 526
$closeButton.Width = 76
$closeButton.Height = 30
$closeButton.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$closeButton.FlatAppearance.BorderColor = $hairline
$closeButton.BackColor = $surface2
$closeButton.ForeColor = $muted
$closeButton.Font = New-UiFont 8.5
$closeButton.Add_Click({ $form.Close() })
$window.Controls.Add($closeButton)

Sync-ShortcutOptions
Sync-RunButton

[void]$form.ShowDialog()
