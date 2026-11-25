[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "SilentlyContinue"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$AiDir = Join-Path $RootDir "ai-service"
$FrontendDir = Join-Path $RootDir "frontend"
$PythonExe = "d:\TailieuNPKH\classbridge\backend\ai-service\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  CLASSBRIDGE FULL-STACK LAUNCHER (Flask :5000 + AI :8000 + Web :4000)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

function Get-PortPids([int]$Port) {
    $lines = netstat -ano | Select-String ":$Port\s+.*LISTENING\s+(\d+)$"
    $pids = @()
    foreach ($m in $lines) {
        if ($m.Line -match "\s+(\d+)\s*$") {
            $procId = [int]$Matches[1]
            if ($procId -gt 0 -and $pids -notcontains $procId) {
                $pids += $procId
            }
        }
    }
    return $pids
}

function Stop-PortProcess([int]$Port) {
    $pids = Get-PortPids $Port
    foreach ($procId in $pids) {
        taskkill /F /T /PID $procId 2>$null | Out-Null
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

# 1. Start Flask Backend (:5000) if not already listening
$flaskPids = Get-PortPids 5000
if ($flaskPids.Count -gt 0) {
    Write-Host "[1/3] Flask Backend (Port 5000) -> RUNNING (http://127.0.0.1:5000)" -ForegroundColor Green
} else {
    Write-Host "[1/3] Starting Flask Backend (Port 5000)..." -ForegroundColor Yellow
    $flaskOut = Join-Path $BackendDir "flask-runtime.out.log"
    $flaskErr = Join-Path $BackendDir "flask-runtime.err.log"
    Start-Process -FilePath $PythonExe -ArgumentList "app.py" -WorkingDirectory $BackendDir -WindowStyle Hidden -RedirectStandardOutput $flaskOut -RedirectStandardError $flaskErr
    Write-Host "      -> Started Flask Backend at http://127.0.0.1:5000" -ForegroundColor Green
}

# 2. Always restart FastAPI AI Service (:8000) with the GPU-enabled Python environment
$aiPids = Get-PortPids 8000
if ($aiPids.Count -gt 0) {
    Write-Host "[2/3] Stopping old process on Port 8000 (PID: $($aiPids -join ', '))..." -ForegroundColor Yellow
    Stop-PortProcess 8000
    Start-Sleep -Milliseconds 600
}
Write-Host "[2/3] Starting FastAPI AI Service (Port 8000) with GPU Python..." -ForegroundColor Yellow
$aiOut = Join-Path $AiDir "ai-runtime.out.log"
$aiErr = Join-Path $AiDir "ai-runtime.err.log"
Start-Process -FilePath $PythonExe -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory $AiDir -WindowStyle Hidden -RedirectStandardOutput $aiOut -RedirectStandardError $aiErr
Write-Host "      -> Started FastAPI AI Service at http://127.0.0.1:8000" -ForegroundColor Green

# 3. Free Port 4000 if an old Next.js process is holding it, then start Next.js Frontend (:4000)
$webPids = Get-PortPids 4000
if ($webPids.Count -gt 0) {
    Write-Host "[3/3] Cleaning up old process on Port 4000 (PID: $($webPids -join ', '))..." -ForegroundColor Yellow
    Stop-PortProcess 4000
    Start-Sleep -Milliseconds 800
}
$lockFile = Join-Path $FrontendDir ".next\dev\lock"
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

Write-Host "[3/3] Starting Next.js Frontend at http://localhost:4000 ..." -ForegroundColor Green
Set-Location $FrontendDir
npx next dev -H 0.0.0.0 -p 4000
