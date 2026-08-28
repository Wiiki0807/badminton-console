param(
    [Parameter(Mandatory = $true)]
    [string]$Endpoint,
    [string]$Token = "",
    [string]$HubEnvFile = "",
    [string]$TaskName = "RocketAI-Line-Reminder-Dispatch"
)

$ErrorActionPreference = "Stop"
$dispatchScript = (Resolve-Path (Join-Path $PSScriptRoot "dispatch-line-reminders.ps1")).Path
if (-not $Token -and $HubEnvFile) {
    $envPath = (Resolve-Path -LiteralPath $HubEnvFile).Path
    $line = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^ROBOT_HUB_TOKEN=' } | Select-Object -First 1
    if (-not $line) {
        throw "ROBOT_HUB_TOKEN is missing from the supplied env file."
    }
    $hubToken = (($line -split '=', 2)[1]).Trim().Trim('"').Trim("'")
    $hmac = [System.Security.Cryptography.HMACSHA256]::new(
        [System.Text.Encoding]::UTF8.GetBytes($hubToken)
    )
    try {
        $digest = $hmac.ComputeHash(
            [System.Text.Encoding]::UTF8.GetBytes("rocketai-line-reminder-dispatch-v1")
        )
        $Token = ([System.BitConverter]::ToString($digest)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $hmac.Dispose()
    }
}
if (-not $Endpoint.StartsWith("https://") -or $Token.Length -lt 32) {
    throw "Provide the production HTTPS endpoint and either -Token or -HubEnvFile."
}

$encodedEndpoint = $Endpoint.Replace("'", "''")
$encodedToken = $Token.Replace("'", "''")
$argument = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$dispatchScript`" -Endpoint '$encodedEndpoint' -Token '$encodedToken'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Installed scheduled task: $TaskName"
