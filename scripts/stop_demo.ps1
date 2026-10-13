$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Stop-ProcessTree([int]$RootProcessId) {
    $Children = Get-CimInstance Win32_Process |
        Where-Object { $_.ParentProcessId -eq $RootProcessId }
    foreach ($Child in $Children) {
        Stop-ProcessTree -RootProcessId $Child.ProcessId
    }
    Stop-Process -Id $RootProcessId -Force
}

foreach ($Name in @("service", "app")) {
    $PidPath = "data\logs\$Name.pid"
    if (Test-Path $PidPath) {
        $ProcessId = Get-Content -LiteralPath $PidPath
        Stop-ProcessTree -RootProcessId $ProcessId
        Remove-Item -LiteralPath $PidPath
        Write-Host "Stopped $Name (PID $ProcessId)"
    }
}

# Older versions stopped only the uv launcher and could leave its Python child.
foreach ($Port in @(8080, 8501)) {
    $Connection = Get-NetTCPConnection -LocalPort $Port -State Listen
    foreach ($Item in $Connection) {
        $Process = Get-CimInstance Win32_Process -Filter "ProcessId = $($Item.OwningProcess)"
        if (
            $Process.CommandLine -like "*src/run_service.py*" -or
            $Process.CommandLine -like "*src/streamlit_app.py*"
        ) {
            Stop-ProcessTree -RootProcessId $Process.ProcessId
            Write-Host "Stopped leftover demo process on port $Port"
        }
    }
}
