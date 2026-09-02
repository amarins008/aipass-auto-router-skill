@echo off
setlocal enabledelayedexpansion
title aipass-auto-router - One Click Launcher
color 0A

REM ============================================================
REM  aipass-oneclick.bat - Launch everything for aipass-auto-router
REM  Chained in scripts/ but invoked from Desktop shortcut.
REM ============================================================

set "SKILL_DIR=%~dp0.."
if not exist "%SKILL_DIR%\SKILL.md" set "SKILL_DIR=E:\My Project\DOM Thaiai\aipass-auto-router"
set "SCRIPTS=%SKILL_DIR%\scripts"
set "STATE=%SKILL_DIR%\state"

echo.
echo  ==============================================
echo    aipass-auto-router - One Click Launcher
echo  ==============================================
echo.

if "%1"=="menu" goto menu

REM ---------------- 0) Locate browser ---------------------
set "BROWSER="
for %%B in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"
  "%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"
) do (
  if exist "%%~B" set "BROWSER=%%~B" & goto have_browser
)
:have_browser
if not defined BROWSER (
  echo  [!] Chrome/Brave not found. Please open the chat manually.
  echo      https://de.aipass.net/chat
)

REM ---------------- 1) Install dependency if missing --------
set "DEP_OK="
python -c "import aiohttp" >nul 2>&1 && set "DEP_OK=1"
if not defined DEP_OK (
  echo  [1/4] Installing dependency ^(aiohttp^)...
  python -m pip install -r "%SKILL_DIR%\requirements.txt" >nul 2>&1
  if errorlevel 1 (
    echo   [!] pip install failed. Run manually:
    echo       python -m pip install -r "%SKILL_DIR%\requirements.txt"
    echo  Trying to continue anyway...
  ) else (
    echo   [OK] aiohttp installed.
  )
) else (
  echo  [1/4] Dependency already installed.
)

REM ---------------- 2) Start CDP browser if not running ----
set "PORT_OPEN="
python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=2)" >nul 2>&1 && set "PORT_OPEN=1"
if not defined PORT_OPEN (
  echo  [2/4] Starting browser with remote-debugging on port 9222...
  set "PROFILE=%LocalAppData%\Chrome\AipassDebug"
  if not exist "%PROFILE%" mkdir "%PROFILE%"
  if defined BROWSER (
    start "" "%BROWSER%" --remote-debugging-port=9222 --user-data-dir="%PROFILE%" "https://de.aipass.net/chat"
    echo   [OK] Browser launched. Please log in if needed.
    echo        Waiting for CDP endpoint...
    timeout /t 5 /nobreak >nul
  ) else (
    echo   [!] No local browser. Open https://de.aipass.net/chat yourself,
    echo       then start the same Chrome with --remote-debugging-port=9222.
  )
) else (
  echo  [2/4] CDP already listening on port 9222.
)

REM ---------------- 3) Verify CDP is reachable ---------------
set "READY="
python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:9222/json',timeout=2)" >nul 2>&1 && set "READY=1"
if defined READY (
  echo  [3/4] CDP connected. Bridge ready.
) else (
  echo  [3/4] CDP not ready yet - opening chat page in default browser.
  start "" "https://de.aipass.net/chat"
)

echo  [4/4] Done. Opening control menu...
echo.

:menu
cls
color 0B
echo  ==============================================
echo    aipass-auto-router  -  Control Center
echo  ==============================================
echo.
echo   1)  Send a task   ^(auto-route by task class^)
echo   2)  Send a task   ^(force Thai content^)
echo   3)  Show model availability  ^(--scan^)
echo   4)  Show cooldown status     ^(--status^)
echo   5)  Clear all cooldowns
echo   6)  Open chat page in browser
echo   0)  Exit
echo.
set "CHOICE="
set /p "CHOICE=  Select [1-6,0]: "

if "%CHOICE%"=="1" goto send_task
if "%CHOICE%"=="2" goto send_thai
if "%CHOICE%"=="3" goto scan
if "%CHOICE%"=="4" goto status
if "%CHOICE%"=="5" goto clear
if "%CHOICE%"=="6" goto open_chat
if "%CHOICE%"=="0" exit /b 0
goto menu

:send_task
echo.
set "TASK="
set /p "TASK=Enter your prompt: "
if not defined TASK (
  echo  No prompt entered. Back to menu.
  timeout /t 2 /nobreak >nul
  goto menu
)
echo.
echo  Routing task through browser (auto-detect class)...
python "%SCRIPTS%\aipass_bridge.py" --task-class fast --prompt "%TASK%"
echo.
pause
goto menu

:send_thai
echo.
set "TASK="
set /p "TASK=Enter Thai prompt: "
if not defined TASK (
  echo  No prompt entered. Back to menu.
  timeout /t 2 /nobreak >nul
  goto menu
)
echo.
echo  Routing as Thai-content task...
python "%SCRIPTS%\aipass_bridge.py" --task-class thai-content --prompt "%TASK%"
echo.
pause
goto menu

:scan
echo.
python "%SCRIPTS%\check_models.py" --scan
echo.
pause
goto menu

:status
echo.
python "%SCRIPTS%\check_models.py" --status
echo.
pause
goto menu

:clear
echo.
python "%SCRIPTS%\check_models.py" --clear-cooldown
echo.
pause
goto menu

:open_chat
echo.
start "" "https://de.aipass.net/chat"
pause
goto menu
