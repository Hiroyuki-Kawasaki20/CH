@echo off
setlocal
rem Start relative to this bat, independent of shortcut working directory.
cd /d "%~dp0"
if errorlevel 1 exit /b 1
set "SELF_TEST="
if /I "%~1"=="--self-test" set "SELF_TEST=-SelfTest"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -File "%~dp0scripts\start_ch_kanban.ps1" %SELF_TEST%
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Startup failed. See the message above and the setup guide.
    if not defined SELF_TEST pause
)
exit /b %EXIT_CODE%
