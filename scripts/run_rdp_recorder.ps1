param(
    [Parameter(Mandatory = $true)]
    [string]$WindowTitle,
    [ValidateSet("unknown", "powershell", "bash")]
    [string]$Shell = "unknown",
    [string]$Output = "rdp-events.jsonl",
    [string]$PythonBin = "python",
    [switch]$RecordMouseMoves,
    [switch]$RecordInjectedKeyEvents
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$collector = Join-Path $rootDir "collectors\WindowsRdpCollector.py"

if (-not (Test-Path -LiteralPath $collector)) {
    throw "RDP collector was not found: $collector"
}

Write-Host "Recording only while the selected mstsc window is active."
Write-Host "Never record passwords, tokens, or other secrets."
$arguments = @($collector, "--window-title", $WindowTitle, "--shell", $Shell, "--output", $Output)
if ($RecordMouseMoves) {
    $arguments += "--record-mouse-moves"
}
if ($RecordInjectedKeyEvents) {
    $arguments += "--record-injected-key-events"
}
& $PythonBin @arguments
