param(
    [string]$OutputPath = (Join-Path $env:TEMP "trainee-terminal-events.jsonl")
)

$ErrorActionPreference = "Stop"

if (-not (Get-Module -ListAvailable -Name PSReadLine)) {
    throw "PSReadLine is required to audit commands in the current PowerShell session."
}

Import-Module PSReadLine
$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}

$global:TraineeTerminalAuditPath = [System.IO.Path]::GetFullPath($OutputPath)
$global:TraineeTerminalAuditSensitivePattern = "password|passcode|secret|token|api[ _-]?key|authorization|bearer|private[ _-]?key|credit[ _-]?card|card[ _-]?number|cvv|cvc|ssn"

Set-PSReadLineOption -AddToHistoryHandler {
    param([string]$Line)

    if (-not [string]::IsNullOrWhiteSpace($Line)) {
        $redacted = $Line -match $global:TraineeTerminalAuditSensitivePattern
        $event = [ordered]@{
            timestamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fff'Z'", [System.Globalization.CultureInfo]::InvariantCulture)
            type = "terminal.command_submitted"
            source = "remote_terminal_audit"
            application = @{ name = "powershell.exe" }
            window = @{ title = "CyberArk remote PowerShell" }
            terminal = @{
                shell = "powershell"
                command = if ($redacted) { "<REDACTED_COMMAND>" } else { $Line }
                content_redacted = $redacted
            }
        }
        $json = $event | ConvertTo-Json -Compress -Depth 5
        [System.IO.File]::AppendAllText(
            $global:TraineeTerminalAuditPath,
            $json + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    return $true
}

function global:Stop-TraineeTerminalAudit {
    Set-PSReadLineOption -AddToHistoryHandler $null
    Remove-Variable -Name TraineeTerminalAuditPath -Scope Global -ErrorAction SilentlyContinue
    Remove-Variable -Name TraineeTerminalAuditSensitivePattern -Scope Global -ErrorAction SilentlyContinue
    Remove-Item -Path Function:\global:Stop-TraineeTerminalAudit -ErrorAction SilentlyContinue
}

Write-Host "Trainee terminal command audit is active for this PowerShell session."
Write-Host "Commands are written to: $global:TraineeTerminalAuditPath"
Write-Host "Run Stop-TraineeTerminalAudit before entering passwords, tokens, or other secrets."
