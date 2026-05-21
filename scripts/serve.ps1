# Serve the web/ folder over http://localhost:8765 and open it in the browser.
# The dashboard can't load via file:// because Babel-in-browser uses fetch() to
# read the .jsx files, and Chrome blocks file:// fetches.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$webDir = Join-Path $root "web"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "venv not found at $py. Run scripts\setup.ps1 first."
}
Push-Location $webDir
try {
    Start-Process "http://localhost:8765/SD%20Sport%20Fishing.html"
    & $py -m http.server 8765
} finally {
    Pop-Location
}
