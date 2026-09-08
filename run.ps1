param(
    [switch]$InstallIfMissing
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopDir = Join-Path $projectRoot "desktop"

if (-not (Test-Path $desktopDir)) {
    throw "Desktop directory not found: $desktopDir"
}

$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    throw "npm not found. Please install Node.js first."
}

$nodeModulesDir = Join-Path $desktopDir "node_modules"
if (-not (Test-Path $nodeModulesDir)) {
    if ($InstallIfMissing) {
        Write-Host "node_modules not found, running npm install in desktop/ ..."
        & $npmCmd.Source install --prefix $desktopDir
    } else {
        throw "desktop/node_modules not found. Run 'npm install --prefix desktop' first, or re-run with -InstallIfMissing."
    }
}

Write-Host "Starting desktop GUI from: $desktopDir"
& $npmCmd.Source --prefix $desktopDir run tauri:dev
