param(
    [string]$WindowTitle,
    [string[]]$ProcessName,
    [ValidateSet("unknown", "powershell", "bash")]
    [string]$Shell = "unknown",
    [string]$Output = "cyberark-events.jsonl",
    [string]$PythonBin = "python",
    [switch]$RecordMouseMoves
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$collector = Join-Path $rootDir "collectors\WindowsCyberArkCollector.py"

if (-not (Test-Path -LiteralPath $collector)) {
    throw "CyberArk collector was not found: $collector"
}

$arguments = @($collector, "--shell", $Shell, "--output", $Output)
if ($WindowTitle) {
    $arguments += @("--window-title", $WindowTitle)
}
foreach ($name in $ProcessName) {
    $arguments += @("--process-name", $name)
}
if ($RecordMouseMoves) {
    $arguments += "--record-mouse-moves"
}

Write-Host "Waiting for an active CyberArk PSM client window."
Write-Host "Never record passwords, tokens, or other secrets."
& $PythonBin @arguments
