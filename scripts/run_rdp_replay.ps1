param(
    [Parameter(Mandatory = $true)]
    [string]$Scenario,
    [Parameter(Mandatory = $true)]
    [string]$WindowTitle,
    [switch]$Execute,
    [switch]$AllowGeometryMismatch,
    [switch]$CheckpointBefore,
    [string]$PythonBin = "python"
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$replay = Join-Path $rootDir "collectors\WindowsRdpReplay.py"

if (-not (Test-Path -LiteralPath $replay)) {
    throw "RDP replay tool was not found: $replay"
}

$arguments = @($replay, $Scenario, "--window-title", $WindowTitle)
if ($Execute) { $arguments += "--execute" }
if ($AllowGeometryMismatch) { $arguments += "--allow-geometry-mismatch" }
if ($CheckpointBefore) { $arguments += "--checkpoint-before" }
& $PythonBin @arguments
