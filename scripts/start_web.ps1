# Start the AxiomScope frontend dev server (expects the API on :8000)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "web")

if (-not (Test-Path "node_modules")) {
    npm install
}
npm run dev
