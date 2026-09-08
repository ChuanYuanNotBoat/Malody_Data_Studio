param(
  [string]$TaskName = "MalodyStatsApiConsistency",
  [string]$Python = "python",
  [string]$BaseUrl = "http://127.0.0.1:18765",
  [string]$DbPath = "data/malody_rankings.db",
  [string]$Modes = "0,3,5",
  [string]$Limits = "20,50",
  [string]$ThresholdRules = '{"quality.issues.":1}'
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$scriptPath = Join-Path $repoRoot "scripts\check_stats_api_consistency.py"
$logDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$outputPath = Join-Path $logDir "scheduled_consistency_report.json"

$args = @(
  $scriptPath,
  "--base-url", $BaseUrl,
  "--db-path", $DbPath,
  "--modes", $Modes,
  "--limits", $Limits,
  "--default-threshold", "0",
  "--threshold-rules", $ThresholdRules,
  "--block-on", "*",
  "--fail-threshold", "0",
  "--output", $outputPath
)

$quotedArgs = $args | ForEach-Object { '"{0}"' -f ($_ -replace '"', '\"') }
$cmd = "$Python $($quotedArgs -join ' ')"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command $cmd"
$trigger = New-ScheduledTaskTrigger -Daily -At 03:30
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Scheduled task installed: $TaskName"
