@echo off
REM Spuštění PlaudSync UI okna.
REM Stačí dvojklik. PLAUDSYNC_STATE_ROOT a další proměnné se načítají z .env.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [chyba] virtualenv chybi: %CD%\.venv
    echo Vytvor: python -m venv .venv ^&^& .venv\Scripts\pip install -e .[dev]
    pause
    exit /b 1
)

if not exist ".env" (
    echo [chyba] .env nenalezen
    echo Zkopiruj .env.example -^> .env a vypln PLAUDSYNC_STATE_ROOT a PLAUD_API_TOKEN.
    pause
    exit /b 1
)

REM Pokud .env neobsahuje neprazdny PLAUDSYNC_STATE_ROOT, dopln default.
findstr /B /R "PLAUDSYNC_STATE_ROOT=." .env >nul 2>&1
if errorlevel 1 (
    echo [info] PLAUDSYNC_STATE_ROOT v .env chybi, doplnuji default C:\PlaudSync
    >>.env echo.
    >>.env echo PLAUDSYNC_STATE_ROOT=C:\PlaudSync
)

REM Build frontend, pokud chybi static\index.html nebo se zmenil zdroj.
if not exist "src\plaudsync\ui\static\index.html" (
    echo [info] frontend bundle chybi, buildim...
    pushd frontend
    if not exist "node_modules" (
        echo [info] node_modules chybi, instaluji...
        call npm install
        if errorlevel 1 (
            popd
            echo [chyba] npm install selhal
            pause
            exit /b 1
        )
    )
    call npm run build
    if errorlevel 1 (
        popd
        echo [chyba] npm run build selhal
        pause
        exit /b 1
    )
    popd
)

.venv\Scripts\python.exe -m plaudsync ui
