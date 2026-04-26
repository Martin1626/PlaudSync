@echo off
REM Manual start for PlaudSync tray (no console window).
REM Double-click in Explorer or run from PowerShell/cmd.
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
start "" /D "%ROOT%" "%ROOT%\.venv\Scripts\pythonw.exe" -m plaudsync tray
endlocal
