# Start trading_workstation in Docker (Windows PowerShell). Idempotent: safe to run repeatedly.
# Usage: .\scripts\start_windows.ps1 [-Build] [-NoOpen]
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$NoOpen,
    [int]$Port = 8000
)
# Native-command failures are checked via $LASTEXITCODE ('Stop' would turn docker stderr into errors on Windows PowerShell 5.1)
$ErrorActionPreference = 'Continue'

$Image = 'trading-workstation'
$Container = 'trading-workstation'
$Volume = 'trading-workstation-data'
$Url = "http://localhost:$Port"
$Root = Split-Path -Parent $PSScriptRoot

function Test-Docker { docker info *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Test-Docker)) {
    Write-Error 'Docker is not running. Start Docker Desktop and try again.'
    exit 1
}

docker image inspect $Image *> $null
if ($Build -or $LASTEXITCODE -ne 0) {
    Write-Host "Building image $Image..."
    docker build -t $Image $Root
    if ($LASTEXITCODE -ne 0) { Write-Error 'Docker build failed.'; exit 1 }
}

# Replace an existing container (running or stopped); the data volume is kept
docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Replacing existing container $Container..."
    docker rm -f $Container *> $null
}

$runArgs = @('run', '-d', '--name', $Container, '-p', "${Port}:8000", '-v', "${Volume}:/app/db")
$envFile = Join-Path $Root '.env'
if (Test-Path $envFile) {
    $runArgs += @('--env-file', $envFile)
} else {
    Write-Warning 'No .env file found; chat will be unavailable. Copy .env.example to .env and set OPENROUTER_API_KEY.'
}
$runArgs += @('-e', 'DB_PATH=/app/db/trading_workstation.db', $Image)

docker @runArgs | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error 'Failed to start the container.'; exit 1 }

Write-Host 'Waiting for the app to become ready...'
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    $running = docker inspect -f '{{.State.Running}}' $Container 2>$null
    if ($running -ne 'true') {
        Write-Host 'Container exited. Logs:'
        docker logs $Container
        exit 1
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) { Write-Warning 'The app did not answer the health check within 60s; it may still be starting.' }

Write-Host "trading_workstation is running at $Url"
Write-Host 'Stop it with .\scripts\stop_windows.ps1 (your data is kept).'

if (-not $NoOpen) { Start-Process $Url }
