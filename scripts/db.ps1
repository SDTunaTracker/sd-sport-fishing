# Pull / push the private data files between this PC and Cloudflare R2.
#
#   scripts\db.ps1 status
#   scripts\db.ps1 pull                      # tracker.db (backs up the local copy first)
#   scripts\db.ps1 pull data/paddies.db
#   scripts\db.ps1 push                      # only if nobody wrote R2 since your pull
#
# Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET in
# .env (see docs/DATA_STORAGE.md). GitHub Actions is the normal writer of
# tracker.db; push from here only for a deliberate local backfill, right
# after a pull, and preferably between the hourly runs (:37 past the hour).
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("pull", "push", "status")]
    [string]$Cmd,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Names = @("tracker.db")
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
Push-Location $root
try {
    if ($Cmd -eq "pull") {
        foreach ($n in $Names) {
            if (Test-Path $n) {
                $bak = "$n.local-$(Get-Date -Format yyyyMMdd-HHmmss)"
                Copy-Item $n $bak
                Write-Host "Backed up local $n -> $bak"
            }
        }
    }
    if ($Cmd -eq "status") { & $py scripts/r2db.py status } else { & $py scripts/r2db.py $Cmd @Names }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
