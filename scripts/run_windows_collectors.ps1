param(
    [string]$PythonBin,
    [string]$ChromeBin,
    [int]$CdpPort = 9222,
    [string]$ProfileDirectory = (Join-Path $HOME ".traineeai-cdp-profile"),
    [int]$DurationSeconds = 0,
    [string]$DesktopOutput = "events.jsonl",
    [double]$DesktopInterval = 0.2,
    [string]$RdpOutput = "rdp-events.jsonl",
    [ValidateSet("unknown", "powershell", "bash")]
    [string]$RdpShell = "unknown",
    [string]$CyberArkOutput = "cyberark-events.jsonl",
    [ValidateSet("unknown", "powershell", "bash")]
    [string]$CyberArkShell = "unknown",
    [string[]]$CyberArkProcessName,
    [switch]$RecordMouseMoves,
    [switch]$RecordInjectedKeyEvents
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$desktopCollector = Join-Path $rootDir "collectors\WindowsCollector.py"
$rdpCollector = Join-Path $rootDir "collectors\WindowsRdpCollector.py"
$cyberarkCollector = Join-Path $rootDir "collectors\WindowsCyberArkCollector.py"
$browserLauncher = Join-Path $PSScriptRoot "run_browser_collector.ps1"
$desktopProcess = $null
$rdpProcess = $null
$cyberarkProcess = $null

if (-not (Test-Path -LiteralPath $desktopCollector)) {
    throw "Windows collector was not found: $desktopCollector"
}
if (-not (Test-Path -LiteralPath $rdpCollector)) {
    throw "RDP collector was not found: $rdpCollector"
}
if (-not (Test-Path -LiteralPath $cyberarkCollector)) {
    throw "CyberArk collector was not found: $cyberarkCollector"
}
if (-not (Test-Path -LiteralPath $browserLauncher)) {
    throw "Browser collector launcher was not found: $browserLauncher"
}
if ($DesktopInterval -le 0) {
    throw "DesktopInterval must be greater than zero."
}

if (-not $PythonBin) {
    $venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"
    $PythonBin = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}

try {
    Write-Host "Starting Windows desktop, browser, RDP, and CyberArk collectors. Press Ctrl+C to stop all."
    Write-Host "Desktop events: $(Join-Path $rootDir $DesktopOutput)"
    Write-Host "RDP events: $(Join-Path $rootDir $RdpOutput)"
    Write-Host "CyberArk events: $(Join-Path $rootDir $CyberArkOutput)"
    $desktopProcess = Start-Process -FilePath $PythonBin -ArgumentList $desktopCollector, "--output", $DesktopOutput, "--interval", $DesktopInterval -WorkingDirectory $rootDir -PassThru -NoNewWindow
    $rdpArguments = @($rdpCollector, "--auto-select", "--output", $RdpOutput, "--shell", $RdpShell)
    if ($RecordMouseMoves) {
        $rdpArguments += "--record-mouse-moves"
    }
    if ($RecordInjectedKeyEvents) {
        $rdpArguments += "--record-injected-key-events"
    }
    $rdpProcess = Start-Process -FilePath $PythonBin -ArgumentList $rdpArguments -WorkingDirectory $rootDir -PassThru -NoNewWindow
    $cyberarkArguments = @($cyberarkCollector, "--output", $CyberArkOutput, "--shell", $CyberArkShell)
    foreach ($name in $CyberArkProcessName) {
        $cyberarkArguments += @("--process-name", $name)
    }
    if ($RecordMouseMoves) {
        $cyberarkArguments += "--record-mouse-moves"
    }
    $cyberarkProcess = Start-Process -FilePath $PythonBin -ArgumentList $cyberarkArguments -WorkingDirectory $rootDir -PassThru -NoNewWindow
    Start-Sleep -Seconds 1
    if ($desktopProcess.HasExited) {
        throw "Windows collector exited immediately with code $($desktopProcess.ExitCode)."
    }
    if ($rdpProcess.HasExited) {
        throw "RDP collector exited immediately with code $($rdpProcess.ExitCode)."
    }
    if ($cyberarkProcess.HasExited) {
        throw "CyberArk collector exited immediately with code $($cyberarkProcess.ExitCode)."
    }

    & $browserLauncher -PythonBin $PythonBin -ChromeBin $ChromeBin -CdpPort $CdpPort -ProfileDirectory $ProfileDirectory -DurationSeconds $DurationSeconds
} finally {
    if ($desktopProcess -and -not $desktopProcess.HasExited) {
        Stop-Process -Id $desktopProcess.Id -ErrorAction SilentlyContinue
    }
    if ($rdpProcess -and -not $rdpProcess.HasExited) {
        Stop-Process -Id $rdpProcess.Id -ErrorAction SilentlyContinue
    }
    if ($cyberarkProcess -and -not $cyberarkProcess.HasExited) {
        Stop-Process -Id $cyberarkProcess.Id -ErrorAction SilentlyContinue
    }
}
