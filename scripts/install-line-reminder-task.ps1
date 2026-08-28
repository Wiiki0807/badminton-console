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

$installDir = Join-Path $env:ProgramData "RocketAI"
$installedScript = Join-Path $installDir "dispatch-line-reminders.ps1"
$tokenFile = Join-Path $installDir "reminder-dispatch-token.txt"
$logFile = Join-Path $installDir "reminder-dispatch.log"
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Copy-Item -LiteralPath $dispatchScript -Destination $installedScript -Force
Set-Content -LiteralPath $tokenFile -Value $Token -NoNewline

$acl = [System.Security.AccessControl.FileSecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
foreach ($sidValue in @("S-1-5-18", "S-1-5-32-544")) {
    $sid = [System.Security.Principal.SecurityIdentifier]::new($sidValue)
    $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $tokenFile -AclObject $acl

$argument = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$installedScript`" -Endpoint $Endpoint -TokenFile `"$tokenFile`" -LogFile `"$logFile`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Installed scheduled task: $TaskName"
Write-Output "Dispatch log: $logFile"
