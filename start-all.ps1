[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "SilentlyContinue"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$AiDir = Join-Path $RootDir "ai-service"
$FrontendDir = Join-Path $RootDir "frontend"

# AI-service Python: prefer a GPU venv that includes FastAPI + PyJWT + python-multipart + Torch
$AiPythonCandidates = @(
    $env:CLASSBRIDGE_AI_PYTHON,
    (Join-Path (Split-Path -Parent $RootDir) ".venv\Scripts\python.exe"),
    (Join-Path $AiDir ".venv\Scripts\python.exe"),
    $env:CLASSBRIDGE_PYTHON,
    (Join-Path $RootDir ".venv\Scripts\python.exe")
)
$AiPythonExe = $null
foreach ($cand in $AiPythonCandidates) {
    if ($cand -and (Test-Path $cand)) {
        & $cand -c "import fastapi, uvicorn, jwt, multipart" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $AiPythonExe = $cand
            break
        }
    }
}
if (-not $AiPythonExe) {
    $AiPythonExe = $AiPythonCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $AiPythonExe) { $AiPythonExe = "python" }

# Flask backend Python: prefer a venv that includes Flask + PyJWT + SQLAlchemy
$BackendPythonCandidates = @(
    $env:CLASSBRIDGE_BACKEND_PYTHON,
    (Join-Path $BackendDir ".venv\Scripts\python.exe"),
    (Join-Path (Split-Path -Parent $RootDir) ".venv\Scripts\python.exe"),
    $env:CLASSBRIDGE_PYTHON,
    (Join-Path $RootDir ".venv\Scripts\python.exe")
)
$BackendPythonExe = $null
foreach ($cand in $BackendPythonCandidates) {
    if ($cand -and (Test-Path $cand)) {
        & $cand -c "import flask, jwt, sqlalchemy" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $BackendPythonExe = $cand
            break
        }
    }
}
if (-not $BackendPythonExe) {
    $BackendPythonExe = $BackendPythonCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $BackendPythonExe) { $BackendPythonExe = "python" }

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  CLASSBRIDGE FULL-STACK LAUNCHER (Flask :5000 + AI :8000 + Web :4000)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

function Get-PortPids([int]$Port) {
    $pids = @()
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        if ($c.OwningProcess -gt 0 -and $pids -notcontains $c.OwningProcess) {
            $pids += [int]$c.OwningProcess
        }
    }
    if ($pids.Count -eq 0) {
        $lines = netstat -ano | Select-String ":$Port\s+"
        foreach ($m in $lines) {
            if ($m.Line -match "\s+(\d+)\s*$") {
                $procId = [int]$Matches[1]
                if ($procId -gt 0 -and $pids -notcontains $procId) {
                    $pids += $procId
                }
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

function Wait-PortFree([int]$Port, [int]$TimeoutMs = 8000) {
    $elapsed = 0
    while ($elapsed -lt $TimeoutMs) {
        if ((Get-PortPids $Port).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 250
        $elapsed += 250
    }
    return ((Get-PortPids $Port).Count -eq 0)
}

function Test-TcpBind([string]$BindIp, [int]$Port) {
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([ipaddress]::Parse($BindIp), $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

# Pre-check Frontend port (default 4000) so FRONTEND_ORIGIN is always accurate for Flask CORS
$webPids = Get-PortPids 4000
if ($webPids.Count -gt 0) {
    Write-Host "[Pre-check] Stopping old process on Port 4000 (PID: $($webPids -join ', '))..." -ForegroundColor Yellow
    Stop-PortProcess 4000
    [void](Wait-PortFree 4000)
}

$WebHost = "0.0.0.0"
$WebPort = 4000
$WebAlreadyServing = $false

if (-not (Test-TcpBind "0.0.0.0" 4000)) {
    try {
        $probe = Invoke-WebRequest -Uri "http://127.0.0.1:4000" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($probe.StatusCode -ge 200 -and $probe.StatusCode -lt 500) {
            $WebAlreadyServing = $true
        }
    } catch {}

    if (-not $WebAlreadyServing) {
        if (Test-TcpBind "127.0.0.1" 4000) {
            $WebHost = "127.0.0.1"
            $WebPort = 4000
        } else {
            $WebHost = "0.0.0.0"
            $WebPort = 4005
            $env:FRONTEND_ORIGIN = "http://localhost:4000,http://localhost:4005,http://127.0.0.1:4005"
            $env:AI_ALLOWED_ORIGINS = "http://localhost:4000,http://127.0.0.1:4000,http://localhost:4005,http://127.0.0.1:4005"
        }
    }
}

# 1. Always restart Flask Backend (:5000) so newly added routes are active (Debug mode is off)
$flaskPids = Get-PortPids 5000
if ($flaskPids.Count -gt 0) {
    Write-Host "[1/3] Stopping old Flask Backend on Port 5000 (PID: $($flaskPids -join ', '))..." -ForegroundColor Yellow
    Stop-PortProcess 5000
    [void](Wait-PortFree 5000)
}
Write-Host "[1/3] Starting Flask Backend (Port 5000)..." -ForegroundColor Yellow
$flaskOut = Join-Path $BackendDir "flask-runtime.out.log"
$flaskErr = Join-Path $BackendDir "flask-runtime.err.log"
Start-Process -FilePath $BackendPythonExe -ArgumentList "app.py" -WorkingDirectory $BackendDir -WindowStyle Hidden -RedirectStandardOutput $flaskOut -RedirectStandardError $flaskErr
Write-Host "      -> Started Flask Backend at http://127.0.0.1:5000" -ForegroundColor Green

# 2. Always restart FastAPI AI Service (:8000) with the GPU-enabled Python environment
$aiPids = Get-PortPids 8000
if ($aiPids.Count -gt 0) {
    Write-Host "[2/3] Stopping old process on Port 8000 (PID: $($aiPids -join ', '))..." -ForegroundColor Yellow
    Stop-PortProcess 8000
    [void](Wait-PortFree 8000)
}
Write-Host "[2/3] Starting FastAPI AI Service (Port 8000) with GPU Python..." -ForegroundColor Yellow
$aiOut = Join-Path $AiDir "ai-runtime.out.log"
$aiErr = Join-Path $AiDir "ai-runtime.err.log"
Start-Process -FilePath $AiPythonExe -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory $AiDir -WindowStyle Hidden -RedirectStandardOutput $aiOut -RedirectStandardError $aiErr
Write-Host "      -> Started FastAPI AI Service at http://127.0.0.1:8000" -ForegroundColor Green

# 3. Start Next.js Frontend (or keep backend/AI alive if Frontend is already serving)
$lockFile = Join-Path $FrontendDir ".next\dev\lock"
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

if ($WebAlreadyServing) {
    Write-Host "[3/3] Next.js Frontend is already running at http://localhost:4000 — keeping Backend (:5000) & AI (:8000) alive..." -ForegroundColor Green
    while ($true) {
        Start-Sleep -Seconds 30
    }
} else {
    Write-Host "[3/3] Starting Next.js Frontend at http://localhost:$WebPort (host $WebHost) ..." -ForegroundColor Green
    Set-Location $FrontendDir
    npx next dev -H $WebHost -p $WebPort
}
