param(
    [Parameter(Mandatory = $true)]
    [string]$Endpoint,
    [string]$Token = "",
    [string]$TokenFile = "",
    [string]$LogFile = ""
)

$ErrorActionPreference = "Stop"
if (-not $Token -and $TokenFile) {
    $Token = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
}
if (-not $Endpoint.StartsWith("https://")) {
    throw "Reminder endpoint must use HTTPS."
}
if ($Token.Length -lt 32) {
    throw "Reminder dispatch token must contain at least 32 characters."
}

try {
    $headers = @{ "X-Line-Reminder-Token" = $Token }
    $result = Invoke-RestMethod -Method Post -Uri $Endpoint -Headers $headers -TimeoutSec 45
    if (-not $result.ok) {
        throw "Reminder dispatch did not return ok=true."
    }
    $line = "$(Get-Date -Format o) OK claimed=$($result.claimed) sent=$($result.sent) failed=$($result.failed)"
    if ($LogFile) {
        Add-Content -LiteralPath $LogFile -Value $line
    }
    $result | ConvertTo-Json -Compress
}
catch {
    if ($LogFile) {
        Add-Content -LiteralPath $LogFile -Value "$(Get-Date -Format o) ERROR $($_.Exception.Message)"
    }
    throw
}
