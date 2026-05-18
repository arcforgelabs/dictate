param(
    [string]$InitialAction = "Install"
)

$ErrorActionPreference = "Stop"
$TermsUrl = "https://arcforge.au/terms"
$DocumentationUrl = "https://github.com/arcforgelabs/dictate#readme"

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

function Invoke-Step {
    param(
        [string]$Label,
        [string]$FilePath,
        [string[]]$Arguments
    )

    Append-Log "==> $Label"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "powershell"
    $psi.Arguments = (
        @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$FilePath`"") + $Arguments
    ) -join " "
    $psi.WorkingDirectory = $PSScriptRoot
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($stdout) { Append-Log $stdout.TrimEnd() }
    if ($stderr) { Append-Log $stderr.TrimEnd() }
    if ($process.ExitCode -ne 0) {
        throw "$Label failed with exit code $($process.ExitCode)."
    }
}

function Invoke-DictateDoctorFix {
    $dictateExe = Join-Path $PSScriptRoot ".venv\Scripts\dictate.exe"
    if (-not (Test-Path $dictateExe)) {
        throw "Dictate is not installed in this source folder. Run Install first."
    }

    Append-Log "==> Repairing Dictate with doctor --fix"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $dictateExe
    $psi.Arguments = "doctor --quick --fix --type-backend pynput"
    $psi.WorkingDirectory = $PSScriptRoot
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($stdout) { Append-Log $stdout.TrimEnd() }
    if ($stderr) { Append-Log $stderr.TrimEnd() }
    if ($process.ExitCode -ne 0) {
        throw "doctor --fix failed with exit code $($process.ExitCode)."
    }
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
            Invoke-Step "Updating Dictate" (Join-Path $PSScriptRoot "update-windows.ps1") $commonArgs
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
