# Start the local AxiomScope API

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing .venv. Run: python -m venv .venv; .\.venv\Scripts\python -m pip install -e '.[dev]'"
}

Write-Host "Starting AxiomScope API on http://127.0.0.1:8000 (MOCK unless AXIOMSCOPE_API_LIVE=true)"
& $python -m county_research_ai.api
