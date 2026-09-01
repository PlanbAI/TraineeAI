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
    [string]$RdpShell = "unknown"
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$desktopCollector = Join-Path $rootDir "collectors\WindowsCollector.py"
$rdpCollector = Join-Path $rootDir "collectors\WindowsRdpCollector.py"
$browserLauncher = Join-Path $PSScriptRoot "run_browser_collector.ps1"
$desktopProcess = $null
$rdpProcess = $null

if (-not (Test-Path -LiteralPath $desktopCollector)) {
    throw "Windows collector was not found: $desktopCollector"
}
if (-not (Test-Path -LiteralPath $rdpCollector)) {
    throw "RDP collector was not found: $rdpCollector"
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
    Write-Host "Starting Windows desktop, browser, and RDP collectors. Press Ctrl+C to stop all."
    Write-Host "Desktop events: $(Join-Path $rootDir $DesktopOutput)"
    Write-Host "RDP events: $(Join-Path $rootDir $RdpOutput)"
    $desktopProcess = Start-Process -FilePath $PythonBin -ArgumentList $desktopCollector, "--output", $DesktopOutput, "--interval", $DesktopInterval -WorkingDirectory $rootDir -PassThru -NoNewWindow
    $rdpProcess = Start-Process -FilePath $PythonBin -ArgumentList $rdpCollector, "--auto-select", "--output", $RdpOutput, "--shell", $RdpShell -WorkingDirectory $rootDir -PassThru -NoNewWindow
    Start-Sleep -Seconds 1
    if ($desktopProcess.HasExited) {
        throw "Windows collector exited immediately with code $($desktopProcess.ExitCode)."
    }
    if ($rdpProcess.HasExited) {
        throw "RDP collector exited immediately with code $($rdpProcess.ExitCode)."
    }

    & $browserLauncher -PythonBin $PythonBin -ChromeBin $ChromeBin -CdpPort $CdpPort -ProfileDirectory $ProfileDirectory -DurationSeconds $DurationSeconds
} finally {
    if ($desktopProcess -and -not $desktopProcess.HasExited) {
        Stop-Process -Id $desktopProcess.Id -ErrorAction SilentlyContinue
    }
    if ($rdpProcess -and -not $rdpProcess.HasExited) {
        Stop-Process -Id $rdpProcess.Id -ErrorAction SilentlyContinue
    }
}
