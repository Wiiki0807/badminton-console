param(
    [Parameter(Mandatory = $true)][string]$GatewayDir
)
$ErrorActionPreference = 'Stop'

$gatewayDir = (Resolve-Path -LiteralPath $GatewayDir).Path
$appDir = Split-Path -Parent $gatewayDir
$envPath = Join-Path $appDir '.env'
$bridgeToken = (& wsl.exe -d Ubuntu-24.04 -- /bin/sed -n 's/^OPENCLAW_BRIDGE_TOKEN=//p' /home/tommywu/.openclaw/.env | Select-Object -Last 1).Trim()
if ($bridgeToken.Length -lt 40) {
    throw 'Unable to read OPENCLAW_BRIDGE_TOKEN from WSL'
}

$lines = if (Test-Path -LiteralPath $envPath) { Get-Content -LiteralPath $envPath } else { @() }
$lines = @($lines | Where-Object { $_ -notmatch '^OPENCLAW_BRIDGE_TOKEN=' })
$lines += "OPENCLAW_BRIDGE_TOKEN=$bridgeToken"
Set-Content -LiteralPath $envPath -Value $lines -Encoding utf8

Stop-ScheduledTask -TaskName 'LineChatGateway' -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName 'LineChatGateway'
Start-Sleep -Seconds 3
$health = Invoke-RestMethod 'http://127.0.0.1:8791/healthz' -TimeoutSec 5
if ($health.status -ne 'ok') {
    throw 'LINE gateway did not recover after restart'
}
Write-Output 'Windows LINE gateway restarted with the OpenClaw bridge token'
