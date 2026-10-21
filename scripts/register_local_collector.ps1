<#
    Register (or remove) the Windows scheduled task that runs the local bridge collector every
    30 minutes. Runs as the current user while logged on (no stored password).

        .\scripts\register_local_collector.ps1             # register and start now
        .\scripts\register_local_collector.ps1 -Status     # show last run result
        .\scripts\register_local_collector.ps1 -Unregister # STOP collection (asks to confirm)

    The PC must stay on, awake and logged in for collection to continue. Check gaps with:
        .\.venv\Scripts\python.exe scripts\collector_status.py
#>
param(
    [switch]$Unregister,
    [switch]$Status,
    [switch]$Force   # skip the -Unregister confirmation
)

$ErrorActionPreference = 'Stop'
$TaskName = 'MoveMelbourne-Collector'
$Repo = Split-Path -Parent $PSScriptRoot

if ($Unregister) {
    if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
        Write-Output "No '$TaskName' task registered; nothing to stop."
        return
    }
    if (-not $Force) {
        Write-Warning "This STOPS data collection for the study. Every minute stopped is lost for good."
        if ((Read-Host "Type STOP to confirm") -ne 'STOP') {
            Write-Output 'Cancelled; collection continues.'
            return
        }
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    # Stopping the task only ends its PowerShell wrapper; the Python collector (venv launcher +
    # interpreter) keeps running, so stop this repo's collector processes explicitly.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*movemelbourne.collect.run_collection*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
    Write-Output "Removed scheduled task '$TaskName' and stopped any running collector."
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
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 35)
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Principal $Principal -Description 'MoveMelbourne GTFS-Realtime collector (29-min poll loop)' -Force | Out-Null
# Bridge the time until the first slot with a one-off run that ENDS before the slot. Starting the
# task itself now would still be running at the slot, and IgnoreNew would skip that whole slot.
$BridgeMin = [math]::Floor(($Start - (Get-Date)).TotalMinutes) - 1
if ($BridgeMin -ge 2) {
    Start-Process powershell.exe -WindowStyle Hidden -WorkingDirectory $Repo -ArgumentList @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "`"$Script`"",
        '-MaxRuntimeMin', "$BridgeMin")
    Write-Output "Bridge run started now for $BridgeMin min."
}
Write-Output "Registered '$TaskName': every 30 min from $($Start.ToString('HH:mm'))."
Write-Output "Logs: $Repo\data\logs\  |  Status: .\scripts\register_local_collector.ps1 -Status"
