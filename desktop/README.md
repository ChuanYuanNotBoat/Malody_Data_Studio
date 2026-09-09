# Malody Data Studio Desktop (Tauri + React)

## Development
1. Install dependencies:
   - `cd desktop`
   - `npm install`
2. Start desktop app:
   - `npm run tauri:dev`

## Runtime assumptions
- The desktop app starts local FastAPI automatically by spawning `python run.py`.
- Default backend address is `http://127.0.0.1:18765`.
- Optional environment variables:
  - `MALODY_PROJECT_DIR` (project root containing `run.py`)
  - `MALODY_API_PYTHON` (python executable path)

## Build
- Frontend only: `npm run build`
- Desktop bundle: `npm run tauri:build`

## Packaging strategy (v1)
- Default: rely on host Python runtime.
- Future: use `scripts/build_desktop_embedded_python.ps1` to prepare embedded runtime packaging pipeline.

