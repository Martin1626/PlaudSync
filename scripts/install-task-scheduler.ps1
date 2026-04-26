<#
.SYNOPSIS
    Register PlaudSync as a Windows Task Scheduler task that launches the
    tray-resident engine at user logon, with auto-restart on failure.

.DESCRIPTION
    PlaudSync v0.3 (tray pivot 2026-04-26): tray proces je sync engine + UI
    launcher v jednom. Task Scheduler ho jednou spustí při loginu a po pádu
    restartuje (3× s 1 min intervalem). Periodic 15-min tick je nahrazen
    in-process SchedulerThread uvnitř tray procesu (schedule.py work-hours
    gate stále funguje stejně).

.PARAMETER ProjectRoot
    Absolute path to the PlaudSync repo (where .venv lives).
.PARAMETER TaskName
    Scheduled task name. Default "PlaudSync".

.EXAMPLE
    PS> .\install-task-scheduler.ps1
.EXAMPLE
    PS> .\install-task-scheduler.ps1 -TaskName "PlaudSyncDev"

.NOTES
    Run as the user that will own the task. Idempotent — if `PlaudSync` task
    already exists (např. starý 15-min tick), je nejdříve odregistrován a
    zaregistrován znova s novou definicí.

    To remove: .\uninstall-task-scheduler.ps1
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "PlaudSync"
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $venvPython)) {
    throw "Python interpreter not found at $venvPython - run 'pip install -e .[dev]' first."
}

$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Warning ".env not found at $envFile - PlaudSync will fail with exit 3 (token missing). Run 'copy .env.example .env' and fill credentials."
}

# Action: pythonw -m plaudsync tray (no console window, tray subcommand)
$action = New-ScheduledTaskAction `
    -Execute $venvPython `
    -Argument "-m plaudsync tray" `
    -WorkingDirectory $ProjectRoot

# Trigger: at user logon (current user only)
$trigger = New-ScheduledTaskTrigger `
    -AtLogOn `
    -User "$env:USERDOMAIN\$env:USERNAME"

# Settings: single instance, restart on failure 3× with 1 min interval
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -DisallowDemandStart:$false

# Run as current user, only when logged on, standard token (not elevated)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Replace existing task if present (idempotent)
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "PlaudSync tray-resident runtime: sync engine + UI launcher. Spustí se při loginu, restart 3× po failure (interval 1 min)." `
    | Out-Null

Write-Host ""
Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  Trigger:    At logon ($env:USERDOMAIN\$env:USERNAME)"
Write-Host "  Action:     $venvPython -m plaudsync tray"
Write-Host "  Restart:    3× po 1 min při failure"
Write-Host "  Run-level:  Limited (standard user token)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Logout + login → tray ikona se objeví v notification area."
Write-Host "  2. Manual start: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  3. Watch logs:   Get-Content '<STATE_ROOT>\plaudsync.log' -Wait -Tail 20"
Write-Host ""
Write-Host "To remove: .\uninstall-task-scheduler.ps1"
