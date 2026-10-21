<#
    Register (or remove) the Windows scheduled task that runs the local bridge collector every
    30 minutes. Runs as the current user while logged on (no stored password).

        .\scripts\register_local_collector.ps1             # register and start now
        .\scripts\register_local_collector.ps1 -Status     # show last run result
        .\scripts\register_local_collector.ps1 -Unregister # remove the task

    The PC must stay on, awake and logged in for collection to continue. Check gaps with:
        uv run python scripts/collector_status.py
#>
param(
    [switch]$Unregister,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$TaskName = 'MoveMelbourne-Collector'
$Repo = Split-Path -Parent $PSScriptRoot

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task '$TaskName'."
    return
}
if ($Status) {
    Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo |
        Select-Object LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns
    return
}

if (-not (Test-Path (Join-Path $Repo '.env'))) {
    throw "No .env in $Repo - copy .env.example to .env and add TVOD_API_KEY first."
}

$Script = Join-Path $PSScriptRoot 'collect_local.ps1'
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`"" `
    -WorkingDirectory $Repo
# Start on the next :00 or :30 and repeat every 30 minutes indefinitely.
$Now = Get-Date
$Start = $Now.Date.AddHours($Now.Hour).AddMinutes([math]::Ceiling(($Now.Minute + 1) / 30) * 30)
$Trigger = New-ScheduledTaskTrigger -Once -At $Start -RepetitionInterval (New-TimeSpan -Minutes 30)
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 35)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Principal $Principal -Description 'MoveMelbourne GTFS-Realtime collector (29-min poll loop)' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Registered '$TaskName': running now, then every 30 min from $($Start.ToString('HH:mm'))."
Write-Output "Logs: $Repo\data\logs\  |  Status: .\scripts\register_local_collector.ps1 -Status"
