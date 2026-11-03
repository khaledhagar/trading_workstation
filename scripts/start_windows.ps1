# Start trading_workstation in Docker. Usage: .\scripts\start_windows.ps1 [-Build] [-NoOpen]
param(
    [switch]$Build,
    [switch]$NoOpen
)
$ErrorActionPreference = "Stop"

$Image = "trading-workstation"
$Container = "trading-workstation"
$Volume = "trading-workstation-data"
$Port = 8000
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"

if (-not (Test-Path $EnvFile)) {
    Write-Host "No .env found; creating one from .env.example (set OPENROUTER_API_KEY for chat)."
    Copy-Item (Join-Path $Root ".env.example") $EnvFile
}

docker image inspect $Image *> $null
if ($Build -or $LASTEXITCODE -ne 0) {
    Write-Host "Building image $Image..."
    docker build -t $Image $Root
    if ($LASTEXITCODE -ne 0) { throw "docker build failed" }
}

# Replace any existing container (idempotent).
docker rm -f $Container *> $null

docker run -d --name $Container `
    -v "${Volume}:/app/db" `
    -p "${Port}:8000" `
    --env-file $EnvFile `
    --restart unless-stopped `
    $Image | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

$Url = "http://localhost:$Port"
Write-Host -NoNewline "Waiting for the app"
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing "$Url/api/health" -TimeoutSec 2 | Out-Null
        break
    } catch {
        Write-Host -NoNewline "."
        Start-Sleep -Seconds 1
    }
}
Write-Host ""
Write-Host "trading_workstation is running at $Url"

if (-not $NoOpen) { Start-Process $Url }
