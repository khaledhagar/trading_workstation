# Stop and remove the trading_workstation container. The data volume is kept.
$Container = "trading-workstation"
$existing = docker ps -a --filter "name=^${Container}$" --format "{{.Names}}"
if ($existing -eq $Container) {
    docker rm -f $Container | Out-Null
    Write-Host "Stopped $Container (data volume kept)."
} else {
    Write-Host "$Container is not running."
}
