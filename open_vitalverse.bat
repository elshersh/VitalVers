@echo off
setlocal
cd /d "%~dp0"
set "URL=http://127.0.0.1:8000/"

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    start "" "%URL%"
    exit /b 0
)

set "PY_EXE="
set "PY_ARG="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=python"
    ) else (
        where py >nul 2>&1
        if not errorlevel 1 (
            set "PY_EXE=py"
            set "PY_ARG=-3"
        )
    )
)

if not defined PY_EXE (
    echo Python 3 was not found. Install Python 3 and run: pip install -r requirements.txt
    pause
    exit /b 1
)

"%PY_EXE%" %PY_ARG% -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo Vitalverse dependencies are missing. Run: pip install -r requirements.txt
    pause
    exit /b 1
)

start "Vitalverse Server" /D "%~dp0" /MIN "%PY_EXE%" %PY_ARG% -m uvicorn app:app --host 127.0.0.1 --port 8000

powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(25); while ((Get-Date) -lt $deadline) { try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 300 }; exit 1" >nul 2>&1
start "" "%URL%"
exit /b 0
