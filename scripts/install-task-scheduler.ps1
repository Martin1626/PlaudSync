<#
.SYNOPSIS
    Register PlaudSync as a Windows Task Scheduler task that ticks every 15 min.

.DESCRIPTION
    PlaudSync's schedule.py decides on each tick whether to actually sync, based
    on work-hours window and last successful sync. So Task Scheduler can fire at
    a fixed short interval (default 15 min) and the gating logic handles the
    "should I run now?" decision.

    This script registers a Per-User scheduled task that runs `python -m plaudsync`
    every 15 minutes while the user is logged on. The user is the current user
    (not SYSTEM) so the task inherits PLAUDSYNC_STATE_ROOT, .env, and Plaud token
    from the user's profile.

.PARAMETER ProjectRoot
    Absolute path to the PlaudSync repo (where .venv lives).
    Defaults to the parent directory of this script.

.PARAMETER TaskName
    Scheduled task name. Defaults to "PlaudSync".

.PARAMETER IntervalMinutes
    Tick interval. Defaults to 15. Schedule.py interval (work_hours_interval_minutes
    in schedule.json) MUST be >= this value, otherwise gating becomes a no-op.

.EXAMPLE
    PS> .\install-task-scheduler.ps1
    PS> .\install-task-scheduler.ps1 -TaskName "PlaudSyncDev" -IntervalMinutes 30

.NOTES
    Run as the user that will own the task (NOT elevated as Administrator unless
    the project also lives in an admin-only path). The task uses -RunLevel Limited
    so it inherits the standard user token.

    To remove: Unregister-ScheduledTask -TaskName "PlaudSync" -Confirm:$false
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "PlaudSync",
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) {
    # Fall back to python.exe if pythonw.exe is missing (rare).
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $venvPython)) {
    throw "Python interpreter not found at $venvPython - run 'pip install -e .[dev]' first."
}

$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Warning ".env not found at $envFile - PlaudSync will fail with exit 3 (token missing). Run 'copy .env.example .env' and fill credentials."
}

# Action: pythonw -m plaudsync (no console window, sync subcommand is default)
$action = New-ScheduledTaskAction `
    -Execute $venvPython `
    -Argument "-m plaudsync" `
    -WorkingDirectory $ProjectRoot

# Trigger: every $IntervalMinutes, indefinitely, starting now
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::FromDays(365 * 10))

# Settings: don't queue parallel runs, give it 5 min to finish (typical sync ~3s/recording)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew `
    -DisallowDemandStart:$false

# Run as current user, only when logged on, standard token (not elevated)
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Replace existing task if present
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
    -Description "PlaudSync periodic sync of Plaud AI recordings. Tick interval: $IntervalMinutes min. Schedule.py gates the actual sync per work-hours window and last-successful-sync elapsed time." `
    | Out-Null

Write-Host ""
Write-Host "Registered scheduled task '$TaskName':"
Write-Host "  Tick interval: $IntervalMinutes min"
Write-Host "  Working dir:   $ProjectRoot"
Write-Host "  Python:        $venvPython"
Write-Host "  User:          $env:USERDOMAIN\$env:USERNAME (Limited token, only when logged on)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Verify task: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  2. Manual run:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  3. Open UI to tune work-hours window: cd '$ProjectRoot'; .\run-ui.bat"
Write-Host "  4. Watch logs:  Get-Content '<STATE_ROOT>\plaudsync.log' -Wait -Tail 20"
Write-Host ""
Write-Host "To remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
