# Start the API (port 8000) and the Vite dev server (port 5173) in two windows.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Virtual environment not found. Run: py -3 -m venv .venv; .venv\Scripts\pip install -e backend[dev]"
    exit 1
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Push-Location (Join-Path $root "frontend"); npm install; Pop-Location
}
Start-Process -WorkingDirectory $root -FilePath $python -ArgumentList "-m", "uvicorn", "docauth.main:app", "--reload", "--reload-dir", "backend", "--port", "8000"
Start-Process -WorkingDirectory (Join-Path $root "frontend") -FilePath "npm.cmd" -ArgumentList "run", "dev"
Write-Host "API: http://127.0.0.1:8000/docs   App: http://localhost:5173"
