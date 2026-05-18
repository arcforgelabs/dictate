param(
    [string]$InitialAction = "Install"
)

$ErrorActionPreference = "Stop"
$TermsUrl = "https://arcforge.au/terms"
$DocumentationUrl = "https://github.com/arcforgelabs/dictate#readme"
$HostedWindowsUpdateUrl = "https://raw.githubusercontent.com/arcforgelabs/dictate/master/update.ps1"

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

$form = New-Object System.Windows.Forms.Form
$form.Text = "Dictate Setup"
$form.StartPosition = "CenterScreen"
$form.Width = 720
$form.Height = 600
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = "Dictate Setup"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
$title.Left = 18
$title.Top = 14
$title.Width = 660
$title.Height = 34
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = "Install, update, repair, or remove Dictate for this Windows user."
$subtitle.Left = 20
$subtitle.Top = 52
$subtitle.Width = 660
$subtitle.Height = 24
$form.Controls.Add($subtitle)

$actionsGroup = New-Object System.Windows.Forms.GroupBox
$actionsGroup.Text = "Action"
$actionsGroup.Left = 18
$actionsGroup.Top = 88
$actionsGroup.Width = 660
$actionsGroup.Height = 140
$form.Controls.Add($actionsGroup)

$actionsGroup.Controls.Add((New-ActionRadio "Install Dictate" "Install" 24 ($InitialAction -eq "Install")))
$actionsGroup.Controls.Add((New-ActionRadio "Update Dictate" "Update" 52 ($InitialAction -eq "Update")))
$actionsGroup.Controls.Add((New-ActionRadio "Repair launchers and runtime checks (doctor --fix)" "Repair" 80 ($InitialAction -eq "Repair")))
$actionsGroup.Controls.Add((New-ActionRadio "Uninstall Dictate" "Uninstall" 108 ($InitialAction -eq "Uninstall")))

$optionsGroup = New-Object System.Windows.Forms.GroupBox
$optionsGroup.Text = "Options"
$optionsGroup.Left = 18
$optionsGroup.Top = 238
$optionsGroup.Width = 660
$optionsGroup.Height = 142
$form.Controls.Add($optionsGroup)

$startupCheck = New-Object System.Windows.Forms.CheckBox
$startupCheck.Text = "Launch on startup"
$startupCheck.Left = 18
$startupCheck.Top = 24
$startupCheck.Width = 180
$startupCheck.Checked = $true
$optionsGroup.Controls.Add($startupCheck)

$shortcutCheck = New-Object System.Windows.Forms.CheckBox
$shortcutCheck.Text = "Create Start Menu entry"
$shortcutCheck.Left = 220
$shortcutCheck.Top = 24
$shortcutCheck.Width = 200
$shortcutCheck.Checked = $true
$shortcutCheck.Add_CheckedChanged({ Sync-ShortcutOptions })
$optionsGroup.Controls.Add($shortcutCheck)

$prepareCheck = New-Object System.Windows.Forms.CheckBox
$prepareCheck.Text = "Prepare default local model"
$prepareCheck.Left = 18
$prepareCheck.Top = 54
$prepareCheck.Width = 220
$prepareCheck.Checked = $true
$optionsGroup.Controls.Add($prepareCheck)

$verifyCheck = New-Object System.Windows.Forms.CheckBox
$verifyCheck.Text = "Run verification"
$verifyCheck.Left = 260
$verifyCheck.Top = 54
$verifyCheck.Width = 160
$verifyCheck.Checked = $true
$optionsGroup.Controls.Add($verifyCheck)

$removeUserDataCheck = New-Object System.Windows.Forms.CheckBox
$removeUserDataCheck.Text = "Also remove user config, logs, history, and models"
$removeUserDataCheck.Left = 18
$removeUserDataCheck.Top = 78
$removeUserDataCheck.Width = 360
$removeUserDataCheck.Checked = $false
$optionsGroup.Controls.Add($removeUserDataCheck)

$termsCheck = New-Object System.Windows.Forms.CheckBox
$termsCheck.Text = "I understand Dictate has real-world risks and agree to the Arc Forge terms"
$termsCheck.Left = 18
$termsCheck.Top = 104
$termsCheck.Width = 500
$termsCheck.Checked = $false
$termsCheck.Add_CheckedChanged({ Sync-RunButton })
$optionsGroup.Controls.Add($termsCheck)

$expectationLabel = New-Object System.Windows.Forms.Label
$expectationLabel.Text = "Support and maintenance are best-effort. Check important output and report issues."
$expectationLabel.Left = 36
$expectationLabel.Top = 124
$expectationLabel.Width = 500
$expectationLabel.Height = 18
$optionsGroup.Controls.Add($expectationLabel)

$termsLink = New-Object System.Windows.Forms.LinkLabel
$termsLink.Text = "Terms"
$termsLink.Left = 548
$termsLink.Top = 105
$termsLink.Width = 52
$termsLink.Add_Click({ Open-ExternalUrl $TermsUrl })
$optionsGroup.Controls.Add($termsLink)

$docsLink = New-Object System.Windows.Forms.LinkLabel
$docsLink.Text = "Documentation"
$docsLink.Left = 548
$docsLink.Top = 124
$docsLink.Width = 120
$docsLink.Add_Click({ Open-ExternalUrl $DocumentationUrl })
$optionsGroup.Controls.Add($docsLink)

$logBox = New-Object System.Windows.Forms.TextBox
$logBox.Left = 18
$logBox.Top = 394
$logBox.Width = 660
$logBox.Height = 116
$logBox.Multiline = $true
$logBox.ScrollBars = "Vertical"
$logBox.ReadOnly = $true
$logBox.Font = New-Object System.Drawing.Font("Consolas", 9)
$form.Controls.Add($logBox)

$runButton = New-Object System.Windows.Forms.Button
$runButton.Text = "Run"
$runButton.Left = 496
$runButton.Top = 524
$runButton.Width = 86
$runButton.Enabled = $false
$runButton.Add_Click({ Start-SelectedAction })
$form.Controls.Add($runButton)

$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text = "Close"
$closeButton.Left = 592
$closeButton.Top = 524
$closeButton.Width = 86
$closeButton.Add_Click({ $form.Close() })
$form.Controls.Add($closeButton)

[void]$form.ShowDialog()
