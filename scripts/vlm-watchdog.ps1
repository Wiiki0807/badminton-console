$ErrorActionPreference = "Stop"

$taskName = "vlmstream"
$healthUrl = "http://127.0.0.1:8090/json"
$logPath = "C:\nvidia\vlm_watchdog.log"

try {
    $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 8
    if ($null -eq $response -or $response.error) {
        throw "LocateAnything returned an unhealthy response"
    }
    exit 0
}
catch {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) task-missing"
        exit 2
    }

    # During model loading the task is Running but 8090 is not ready yet. Do not
    # issue overlapping starts; the next watchdog run will verify it again.
    if ($task.State -ne "Running") {
        Add-Content -LiteralPath $logPath -Value "$(Get-Date -Format o) health-failed state=$($task.State) starting-task"
        Start-ScheduledTask -TaskName $taskName
    }
    exit 0
}
