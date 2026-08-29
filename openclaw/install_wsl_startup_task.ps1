$ErrorActionPreference = 'Stop'
$taskName = 'OpenClawWSLStartup'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\wsl.exe" `
    -Argument '-d Ubuntu-24.04 -- /bin/true'
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Start the cam owner WSL distro so lingering OpenClaw services start after boot' `
    -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output "Installed $taskName for $identity with S4U (no stored password)"
