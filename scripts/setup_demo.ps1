$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$env:PATH = [Environment]::GetEnvironmentVariable("PATH", "User") + ";" +
    [Environment]::GetEnvironmentVariable("PATH", "Machine")

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Run: winget install --id astral-sh.uv -e"
}

Write-Host "[1/5] Installing the project Python and dependencies..." -ForegroundColor Cyan
uv python install 3.12
uv sync --frozen

Write-Host "[2/5] Creating the offline demo configuration..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item -LiteralPath ".env.mock.example" -Destination ".env"
}

Write-Host "[3/5] Initializing the fake order database..." -ForegroundColor Cyan
$env:PYTHONPATH = "src"
uv run python -c "from customer_support.store import initialize_database; print(initialize_database())"

Write-Host "[4/5] Building and evaluating the local RAG index..." -ForegroundColor Cyan
Write-Host "The first run downloads a Chinese embedding model of about 90 MB."
uv run python scripts/evaluate_rag.py

Write-Host "[5/5] Running core automated tests..." -ForegroundColor Cyan
uv run pytest tests/customer_support -q

Write-Host ""
Write-Host "Setup complete. Next run: .\scripts\start_demo.cmd" -ForegroundColor Green
