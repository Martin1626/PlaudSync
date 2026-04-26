@echo off
REM Manual start for PlaudSync tray (no console window).
REM Double-click this file in Explorer, or run from PowerShell/cmd.
REM /D sets CWD so dotenv finds .env in project root.
start "" /D "%~dp0.." "%~dp0..\.venv\Scripts\pythonw.exe" -m plaudsync tray
