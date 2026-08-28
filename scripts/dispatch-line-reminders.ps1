param(
    [Parameter(Mandatory = $true)]
    [string]$Endpoint,
    [Parameter(Mandatory = $true)]
    [string]$Token
)

$ErrorActionPreference = "Stop"
if (-not $Endpoint.StartsWith("https://")) {
    throw "Reminder endpoint must use HTTPS."
}
if ($Token.Length -lt 32) {
    throw "Reminder dispatch token must contain at least 32 characters."
}

$headers = @{ "X-Line-Reminder-Token" = $Token }
$result = Invoke-RestMethod -Method Post -Uri $Endpoint -Headers $headers -TimeoutSec 45
if (-not $result.ok) {
    throw "Reminder dispatch did not return ok=true."
}
$result | ConvertTo-Json -Compress
