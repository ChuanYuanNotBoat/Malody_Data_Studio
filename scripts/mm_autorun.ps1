param(
    [int]$IntervalMinutes = 30,
    [int]$MmLimit = 200,
    [string]$ProjectRoot = "F:\projects\tools\working\malody_tools\malody_api",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Continue"

if ($IntervalMinutes -lt 5) {
    $IntervalMinutes = 5
}

if (-not (Test-Path $ProjectRoot)) {
    throw "Project root not found: $ProjectRoot"
}

Set-Location $ProjectRoot
New-Item -ItemType Directory -Path ".\logs" -Force | Out-Null

$schedulerLog = ".\logs\mm_scheduler.log"
$lastRunLog = ".\logs\mm_scheduler_last_run.log"

function Resolve-PythonExecutable {
    param(
        [Parameter(Mandatory = $false)]
        [string]$PreferredPath
    )

    if ($PreferredPath) {
        if (Test-Path $PreferredPath) {
            return @{ exe = $PreferredPath; prefix = @() }
        }
        throw "Configured PythonPath not found: $PreferredPath"
    }

    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{ exe = $venvPython; prefix = @() }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @{ exe = $pythonCmd.Source; prefix = @() }
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @{ exe = $pyCmd.Source; prefix = @("-3") }
    }

    throw "Python executable not found. Set -PythonPath or install Python/py launcher."
}

$pythonConfig = Resolve-PythonExecutable -PreferredPath $PythonPath
$pythonExe = $pythonConfig.exe
$pythonPrefix = $pythonConfig.prefix
$initTs = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $schedulerLog -Value "[$initTs] MM scheduler started. python=$pythonExe interval=${IntervalMinutes}m mm_limit=$MmLimit"

while ($true) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $schedulerLog -Value "[$timestamp] MM scheduler tick."
    try {
        $runArgs = @()
        $runArgs += $pythonPrefix
        $runArgs += @(".\crawlers\rankings.py", "--mm-only", "--mm-limit", "$MmLimit")
        $runOutput = & $pythonExe @runArgs 2>&1 | ForEach-Object { $_.ToString() }
        $runOutput | Set-Content -Path $lastRunLog -Encoding UTF8
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Add-Content -Path $schedulerLog -Value "[$timestamp] MM run exited with code $exitCode"
        }
    } catch {
        $errTs = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $schedulerLog -Value "[$errTs] MM run failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds ($IntervalMinutes * 60)
}
