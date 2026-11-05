@echo off
setlocal enabledelayedexpansion
title MLBFD Server & Tunnel Launcher

echo ======================================================================
echo   MLBFD: Machine Learning Based Fraud Detection Launcher
echo ======================================================================

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"
if not exist "%SCRIPT_DIR%logs" mkdir "%SCRIPT_DIR%logs"

:: Check virtual environment
if exist "%SCRIPT_DIR%backend\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%backend\.venv\Scripts\python.exe"
) else if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [*] Using Python: %PYTHON_EXE%

:: A server started before an .env edit keeps the OLD values; refuse to start a second copy.
netstat -ano -p TCP | findstr /R /C:":5000 .*LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [!] Something is already listening on port 5000. Stop it first ^(it may hold old .env values^):
    netstat -ano -p TCP | findstr /R /C:":5000 .*LISTENING"
    echo     Stop-Process -Id ^<PID^>   then run this launcher again.
    pause
    exit /b 1
)

:: Check if cloudflared is installed
set "TUNNEL_LOG=%SCRIPT_DIR%logs\cloudflared.log"
where cloudflared >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    if exist "%TUNNEL_LOG%" del /q "%TUNNEL_LOG%"
    echo [*] Cloudflared detected. Starting quick tunnel in a separate window...
    start "Cloudflare Tunnel" /min cmd /c cloudflared tunnel --no-autoupdate --url http://localhost:5000 --logfile "%TUNNEL_LOG%"
    powershell -NoProfile -Command "$f=$env:TUNNEL_LOG; for($i=0;$i -lt 40;$i++){ if(Test-Path $f){ $m=Select-String -Path $f -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if($m){ Write-Host ''; Write-Host ('[PUBLIC URL] ' + $m.Matches[0].Value) -ForegroundColor Green; Write-Host '             share this link; admin pages stay local-only unless ADMIN_API_TOKEN is set'; exit 0 } }; Start-Sleep -Seconds 1 }; Write-Host '[!] Tunnel URL not seen within 40 s; check the Cloudflare Tunnel window / logs\cloudflared.log'"
) else (
    echo [!] Cloudflared was not found in PATH.
    echo [*] To enable public HTTPS access, install cloudflared:
    echo     winget install --id Cloudflare.cloudflared
    echo [*] See README_HOSTING.md for complete instructions.
)

echo.
echo [*] Starting MLBFD server on http://localhost:5000 ...
"%PYTHON_EXE%" serve.py

pause
