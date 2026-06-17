# One command to run the whole stack on Windows: API + agent worker + simulator
# + Next.js frontend. Press Ctrl+C to stop everything.
#
#   powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1
#
# Native orchestrator (no honcho/bash): honcho is unusable here because the
# system 'bash' resolves to WSL. This launches each service directly with the
# project venv and npm, shares one console, and kills the whole tree on exit.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  throw "venv python not found at $py. Create the venv and: pip install -r requirements.txt -r requirements-dev.txt"
}

function Stop-Stack {
  # taskkill /T kills the whole tree, so uvicorn's --reload worker (whose command
  # line doesn't match the regex) dies with its reloader parent.
  # Let cmd do the redirection so a "process not found" race (the PID died as a
  # child of one already killed) can't surface as a PowerShell NativeCommandError.
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "ingestor_service|agent_worker|simulator_service|uvicorn" } |
    ForEach-Object { cmd /c "taskkill /PID $($_.ProcessId) /T /F >nul 2>nul" }
  Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -match "next-server|next dev" } |
    ForEach-Object { cmd /c "taskkill /PID $($_.ProcessId) /T /F >nul 2>nul" }
}

Write-Host "Clearing any existing stack instances..." -ForegroundColor Cyan
Stop-Stack

# Redis is infrastructure - not managed here. Warn if it isn't reachable.
$redisOk = (Test-NetConnection -ComputerName 127.0.0.1 -Port 6379 -WarningAction SilentlyContinue).TcpTestSucceeded
if (-not $redisOk) {
  Write-Warning "Redis is not reachable on 127.0.0.1:6379 - the agent needs it."
  Write-Warning "Start it first, e.g.:  docker run -d -p 6379:6379 redis"
}

$procs = @()
function Launch($name, $file, $argList, $workdir) {
  Write-Host "  -> starting $name" -ForegroundColor Green
  $p = Start-Process -FilePath $file -ArgumentList $argList -WorkingDirectory $workdir -NoNewWindow -PassThru
  $script:procs += $p
}

try {
  Launch "api"   $py @("-m","uvicorn","ingestor_service.app:app","--host","0.0.0.0","--port","8000","--reload") $root
  Launch "agent" $py @("-m","agent_worker.main") $root
  Launch "sim"   $py @("-m","simulator_service.main","--base-url","http://127.0.0.1:8000","--deterministic-demo") $root
  Launch "web"   "npm.cmd" @("run","dev") (Join-Path $root "frontend")

  Write-Host "`nStack is up. Dashboard: http://localhost:3000  (API on :8000)" -ForegroundColor Cyan
  Write-Host "Press Ctrl+C to stop everything.`n" -ForegroundColor Cyan

  # Block until Ctrl+C; the finally block tears the whole stack down.
  while ($true) { Start-Sleep -Seconds 1 }
}
finally {
  Write-Host "`nStopping all services..." -ForegroundColor Cyan
  foreach ($p in $procs) {
    cmd /c "taskkill /PID $($p.Id) /T /F >nul 2>nul"
  }
  Stop-Stack
  Write-Host "All stopped." -ForegroundColor Cyan
}
