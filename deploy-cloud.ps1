[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "SilentlyContinue"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$AiDir = Join-Path $RootDir "ai-service"

$CloudflaredCandidates = @(
    (Get-Command cloudflared -ErrorAction SilentlyContinue).Source,
    "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    "C:\Program Files\cloudflared\cloudflared.exe",
    "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe"
)
$CloudflaredExe = $CloudflaredCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $CloudflaredExe) {
    Write-Host "ERROR: cloudflared is not installed. Run: winget install --id Cloudflare.cloudflared -e" -ForegroundColor Red
    exit 1
}

$AiPythonCandidates = @(
    $env:CLASSBRIDGE_AI_PYTHON,
    (Join-Path (Split-Path -Parent $RootDir) ".venv\Scripts\python.exe"),
    (Join-Path $AiDir ".venv\Scripts\python.exe"),
    (Join-Path $RootDir ".venv\Scripts\python.exe")
)
$AiPythonExe = $null
foreach ($cand in $AiPythonCandidates) {
    if ($cand -and (Test-Path $cand)) {
        & $cand -c "import fastapi, uvicorn, jwt, multipart, httpx" 2>$null
        if ($LASTEXITCODE -eq 0) { $AiPythonExe = $cand; break }
    }
}
if (-not $AiPythonExe) { $AiPythonExe = "python" }

$BackendPythonCandidates = @(
    $env:CLASSBRIDGE_BACKEND_PYTHON,
    (Join-Path $BackendDir ".venv\Scripts\python.exe"),
    (Join-Path (Split-Path -Parent $RootDir) ".venv\Scripts\python.exe"),
    (Join-Path $RootDir ".venv\Scripts\python.exe")
)
$BackendPythonExe = $null
foreach ($cand in $BackendPythonCandidates) {
    if ($cand -and (Test-Path $cand)) {
        & $cand -c "import flask, jwt, sqlalchemy" 2>$null
        if ($LASTEXITCODE -eq 0) { $BackendPythonExe = $cand; break }
    }
}
if (-not $BackendPythonExe) { $BackendPythonExe = "python" }

function Get-PortPids([int]$Port) {
    $pids = @()
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        if ($c.OwningProcess -gt 0 -and $pids -notcontains $c.OwningProcess) {
            $pids += [int]$c.OwningProcess
        }
    }
    return $pids
}

function Stop-PortProcess([int]$Port) {
    foreach ($procId in (Get-PortPids $Port)) {
        taskkill /F /T /PID $procId 2>$null | Out-Null
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Stop-PortProcess 5000
Stop-PortProcess 8000
Start-Sleep -Seconds 1

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  CLASSBRIDGE UNIFIED CLOUD GATEWAY (Flask :5000 + AI GPU :8000)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

$env:ALLOW_LAN_ORIGINS = "1"
$env:AI_ALLOW_LAN_ORIGINS = "1"

$flaskOut = Join-Path $BackendDir "flask-runtime.out.log"
$flaskErr = Join-Path $BackendDir "flask-runtime.err.log"
Start-Process -FilePath $BackendPythonExe -ArgumentList "app.py" -WorkingDirectory $BackendDir -WindowStyle Hidden -RedirectStandardOutput $flaskOut -RedirectStandardError $flaskErr
Write-Host "[1/3] Started Flask Backend (:5000)" -ForegroundColor Green

$aiOut = Join-Path $AiDir "ai-runtime.out.log"
$aiErr = Join-Path $AiDir "ai-runtime.err.log"
Start-Process -FilePath $AiPythonExe -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000" -WorkingDirectory $AiDir -WindowStyle Hidden -RedirectStandardOutput $aiOut -RedirectStandardError $aiErr
Write-Host "[2/3] Started Unified FastAPI Gateway + AI GPU (:8000)" -ForegroundColor Green

$cfLog = Join-Path $RootDir "tunnel-gateway.log"
Remove-Item $cfLog, (Join-Path $RootDir "tunnel-backend.log"), (Join-Path $RootDir "tunnel-ai.log") -Force -ErrorAction SilentlyContinue

Start-Process -FilePath $CloudflaredExe -ArgumentList "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate", "--logfile", $cfLog -WindowStyle Hidden
Write-Host "[3/3] Opening public HTTPS Cloudflare Tunnel..." -ForegroundColor Yellow

$GatewayHttps = $null
$elapsed = 0
while ($elapsed -lt 35) {
    if (Test-Path $cfLog) {
        $content = Get-Content $cfLog -Raw -ErrorAction SilentlyContinue
        if ($content -match "(https://[a-zA-Z0-9-]+\.trycloudflare\.com)") {
            $GatewayHttps = $Matches[1]
            break
        }
    }
    Start-Sleep -Seconds 1
    $elapsed += 1
}

$tunnelInfo = @{
    GATEWAY_HTTPS_URL        = $GatewayHttps
    NEXT_PUBLIC_API_BASE_URL = $GatewayHttps
    NEXT_PUBLIC_AI_URL       = $GatewayHttps
    updatedAt                = (Get-Date).ToString("o")
}
$tunnelJsonPath = Join-Path $RootDir "tunnel-urls.json"
$tunnelInfo | ConvertTo-Json | Set-Content -Path $tunnelJsonPath -Encoding UTF8

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  PUBLIC HTTPS GATEWAY READY!" -ForegroundColor Green
Write-Host "  GATEWAY URL (API + AI + WSS) = $GatewayHttps" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Green

while ($true) {
    Start-Sleep -Seconds 30
}
