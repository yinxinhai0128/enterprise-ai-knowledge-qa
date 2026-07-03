$root = $PSScriptRoot
$frontend = Join-Path $root "frontend"

Write-Host "Starting backend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .venv\Scripts\Activate.ps1; uvicorn app.main:app --host 127.0.0.1 --port 8765" -WindowStyle Normal

Start-Sleep -Seconds 3

Write-Host "Starting worker..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .venv\Scripts\Activate.ps1; python -m app.worker" -WindowStyle Normal

Write-Host "Starting frontend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontend'; npm run dev" -WindowStyle Normal

Start-Sleep -Seconds 4
Write-Host ""
Write-Host "All started. Open: http://localhost:5173" -ForegroundColor Green
Write-Host ""
Write-Host "First run? Create an admin account:" -ForegroundColor Yellow
Write-Host "  .venv\Scripts\python.exe scripts\create_admin.py --username admin --password YourPassword" -ForegroundColor Gray
