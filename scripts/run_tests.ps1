$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User") + ";" +
    [Environment]::GetEnvironmentVariable("PATH", "Machine")

Write-Host "Running unit tests..." -ForegroundColor Cyan
uv run pytest tests/customer_support -q

$CustomerSupportMode = [Environment]::GetEnvironmentVariable("CUSTOMER_SUPPORT_MODE", "Process")
if ([string]::IsNullOrWhiteSpace($CustomerSupportMode)) {
    $EnvLines = Get-Content -LiteralPath ".env" -ErrorAction SilentlyContinue
    foreach ($EnvLine in $EnvLines) {
        if ($EnvLine -match '^\s*(?:export\s+)?CUSTOMER_SUPPORT_MODE\s*=\s*(.*)$') {
            $ConfiguredMode = $Matches[1].Trim()
            if ($ConfiguredMode -match '^([''"])(.*?)\1\s*(?:#.*)?$') {
                $CustomerSupportMode = $Matches[2]
            }
            else {
                $CustomerSupportMode = ($ConfiguredMode -split '\s+#', 2)[0].Trim()
            }
        }
    }
}
$ForcesMock = $CustomerSupportMode -and $CustomerSupportMode.Trim().ToLowerInvariant() -eq "mock"

Write-Host ""
if (-not $ForcesMock) {
    Write-Host "An explicit mock configuration was not detected." -ForegroundColor Yellow
    Write-Host "Skipping the 9-case HTTP batch to avoid unintended API charges."
    Write-Host "Use the three manual UI checks in START_HERE.md instead."
}
else {
    Write-Host "Running offline HTTP end-to-end checks..." -ForegroundColor Cyan
    uv run python scripts/demo_check.py
}
