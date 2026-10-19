# Delivery Gates and DoD

## Merge Gates (required)
1. Unit tests:
   - `python -m unittest discover -s tests -t . -p "test_*.py" -v`
2. Compile check:
   - `python -m compileall -q .`
3. Stats/API consistency gate:
   - `python scripts/check_stats_api_consistency.py ...`

Use one-shot runner:
- `powershell -ExecutionPolicy Bypass -File scripts/run_pre_merge_gate.ps1`

## Definition of Done (DoD)
Every task must include:
1. Implementation (code or script change)
2. Tests (new or updated)
3. Minimal docs/notes updates
4. Acceptance evidence:
   - command output, report file, or test pass result

## Consistency Scheduling
- Install scheduled check:
  - `powershell -ExecutionPolicy Bypass -File scripts/install_consistency_task.ps1`
- Default output:
  - `logs/scheduled_consistency_report.json`
