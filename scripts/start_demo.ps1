$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User") + ";" +
    [Environment]::GetEnvironmentVariable("PATH", "Machine")
$UvPath = (Get-Command uv -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null

function Test-Url([string]$Url) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-Url "http://127.0.0.1:8080/health")) {
    Write-Host "Starting the FastAPI service..." -ForegroundColor Cyan
    $Service = Start-Process -FilePath $UvPath `
        -ArgumentList @("run", "python", "src/run_service.py") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput "data\logs\service.out.log" `
        -RedirectStandardError "data\logs\service.err.log" `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath "data\logs\service.pid" -Value $Service.Id
}

$ServiceReady = $false
for ($i = 0; $i -lt 30; $i++) {
    if (Test-Url "http://127.0.0.1:8080/health") {
        $ServiceReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ServiceReady) {
    Get-Content -LiteralPath "data\logs\service.err.log" -Tail 50
    throw "FastAPI failed to start. Send the log above to Codex."
}

if (-not (Test-Url "http://127.0.0.1:8501/_stcore/health")) {
    Write-Host "Starting the Streamlit app..." -ForegroundColor Cyan
    $App = Start-Process -FilePath $UvPath `
        -ArgumentList @(
            "run", "streamlit", "run", "src/streamlit_app.py",
            "--server.address", "127.0.0.1",
            "--server.port", "8501",
            "--server.headless", "true"
        ) `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput "data\logs\app.out.log" `
        -RedirectStandardError "data\logs\app.err.log" `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath "data\logs\app.pid" -Value $App.Id
}

$AppReady = $false
for ($i = 0; $i -lt 30; $i++) {
    if (Test-Url "http://127.0.0.1:8501/_stcore/health") {
        $AppReady = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $AppReady) {
    Get-Content -LiteralPath "data\logs\app.err.log" -Tail 50
    throw "Streamlit failed to start. Send the log above to Codex."
}

Write-Host ""
Write-Host "Demo started: http://127.0.0.1:8501" -ForegroundColor Green
Write-Host "Stop it with: .\scripts\stop_demo.cmd"
Start-Process "http://127.0.0.1:8501"
