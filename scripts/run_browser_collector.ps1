param(
    [string]$PythonBin,
    [string]$ChromeBin,
    [int]$CdpPort = 9222,
    [string]$ProfileDirectory = (Join-Path $HOME ".traineeai-cdp-profile"),
    [int]$DurationSeconds = 0
)

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $PSScriptRoot
$collector = Join-Path $rootDir "collectors\BrowserCollector.py"
$cdpUrl = "http://127.0.0.1:$CdpPort/json/version"
$startedChrome = $false
$collectorProcess = $null
$chromeProcess = $null

function Test-CdpReady {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.BeginConnect("127.0.0.1", $CdpPort, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($connection)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Find-Chrome {
    param([string]$ConfiguredPath)

    if ($ConfiguredPath) {
        if (Test-Path -LiteralPath $ConfiguredPath) {
            return $ConfiguredPath
        }
        throw "Chrome executable was not found: $ConfiguredPath"
    }

    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LocalAppData\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw "Chrome, Chromium, or Edge was not found. Pass -ChromeBin with the browser executable path."
}

if (-not (Test-Path -LiteralPath $collector)) {
    throw "Browser collector was not found: $collector"
}

if (-not $PythonBin) {
    $venvPython = Join-Path $rootDir ".venv\Scripts\python.exe"
    $PythonBin = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}

try {
    if (-not (Test-CdpReady)) {
        $ChromeBin = Find-Chrome $ChromeBin
        New-Item -ItemType Directory -Force -Path $ProfileDirectory | Out-Null
        $chromeArguments = @(
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=$CdpPort",
            "--user-data-dir=$ProfileDirectory",
            "--no-first-run",
            "--no-default-browser-check"
        )
        $chromeProcess = Start-Process -FilePath $ChromeBin -ArgumentList $chromeArguments -PassThru
        $startedChrome = $true

        for ($attempt = 0; $attempt -lt 40 -and -not (Test-CdpReady); $attempt++) {
            Start-Sleep -Milliseconds 250
        }
        if (-not (Test-CdpReady)) {
            throw "Chrome started but CDP is unavailable at $cdpUrl"
        }
    }

    Write-Host "Browser collector: $collector"
    Write-Host "CDP endpoint: $cdpUrl"
    Write-Host "Events file: $(Join-Path $rootDir 'browser-events.jsonl')"
    $env:CDP_HOST = "127.0.0.1"
    $env:CDP_PORT = $CdpPort
    $collectorProcess = Start-Process -FilePath $PythonBin -ArgumentList $collector -WorkingDirectory $rootDir -PassThru -NoNewWindow
    Start-Sleep -Seconds 1
    if ($collectorProcess.HasExited) {
        throw "Browser collector exited immediately with code $($collectorProcess.ExitCode)."
    }

    if ($DurationSeconds -gt 0) {
        Write-Host "Collector will stop after $DurationSeconds second(s)."
        Start-Sleep -Seconds $DurationSeconds
    } else {
        Write-Host "Collector is running. Press Ctrl+C to stop."
        Wait-Process -Id $collectorProcess.Id
    }
} finally {
    if ($collectorProcess -and -not $collectorProcess.HasExited) {
        Stop-Process -Id $collectorProcess.Id -ErrorAction SilentlyContinue
    }
    if ($startedChrome -and $chromeProcess -and -not $chromeProcess.HasExited) {
        Stop-Process -Id $chromeProcess.Id -ErrorAction SilentlyContinue
    }
}
