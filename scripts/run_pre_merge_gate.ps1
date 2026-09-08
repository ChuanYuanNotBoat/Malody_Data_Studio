param(
  [string]$Python = "python",
  [string]$BaseUrl = "http://127.0.0.1:18765",
  [string]$DbPath = "data/malody_rankings.db",
  [string]$Modes = "0,3,5",
  [string]$Limits = "20,50",
  [double]$DefaultThreshold = 0,
  [string]$ThresholdRules = '{"quality.issues.":1}'
)

$ErrorActionPreference = "Stop"

Write-Host "== Gate 1/3: unit tests =="
& $Python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Gate 2/3: compileall =="
& $Python -m compileall -q run.py app routers core utils cli stats_cli crawlers scripts tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== Gate 3/3: stats/api consistency =="
& $Python scripts/check_stats_api_consistency.py `
  --base-url $BaseUrl `
  --db-path $DbPath `
  --modes $Modes `
  --limits $Limits `
  --default-threshold $DefaultThreshold `
  --threshold-rules $ThresholdRules `
  --block-on "*" `
  --fail-threshold 0
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "All gates passed."
