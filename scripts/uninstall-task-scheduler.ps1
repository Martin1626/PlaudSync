<#
.SYNOPSIS
    Unregister PlaudSync scheduled task.

.PARAMETER TaskName
    Default "PlaudSync".

.PARAMETER CleanupLocks
    Switch — pokud zadán, smaže i tray.lock + paused.flag z ${PLAUDSYNC_STATE_ROOT}/.plaudsync/.

.EXAMPLE
    PS> .\uninstall-task-scheduler.ps1
.EXAMPLE
    PS> .\uninstall-task-scheduler.ps1 -CleanupLocks
#>
[CmdletBinding()]
param(
    [string]$TaskName = "PlaudSync",
    [switch]$CleanupLocks
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Removing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed."
} else {
    Write-Host "Task '$TaskName' not found — nothing to remove."
}

if ($CleanupLocks) {
    $stateRoot = $env:PLAUDSYNC_STATE_ROOT
    if ($stateRoot -and (Test-Path $stateRoot)) {
        $lockDir = Join-Path $stateRoot ".plaudsync"
        foreach ($name in @("tray.lock", "paused.flag")) {
            $p = Join-Path $lockDir $name
            if (Test-Path $p) {
                Remove-Item $p -Force
                Write-Host "Removed: $p"
            }
        }
    } else {
        Write-Warning "PLAUDSYNC_STATE_ROOT not set or path missing; skip lock cleanup."
    }
}
