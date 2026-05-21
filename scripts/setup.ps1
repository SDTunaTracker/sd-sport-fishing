# One-time setup: create .venv and install Python dependencies.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$py = (Get-Command py -ErrorAction SilentlyContinue).Source
if (-not $py) {
    Write-Error "Python launcher 'py' not found. Install Python 3 from python.org first."
}
if (-not (Test-Path $venv)) {
    Write-Output "Creating venv at $venv"
    & $py -3 -m venv $venv
}
$venvPy = Join-Path $venv "Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r (Join-Path $root "requirements.txt")
Write-Output ""
Write-Output "Setup complete. Next steps:"
Write-Output "  scripts\run-daily.ps1    # one manual run"
Write-Output "  scripts\install-task.ps1 # schedule the daily run"
Write-Output "  scripts\serve.ps1        # view the dashboard"
