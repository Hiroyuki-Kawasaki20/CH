@echo off
setlocal

rem Always run from this script directory.
cd /d "%~dp0"

set "SELF_TEST=0"
if /I "%~1"=="--self-test" set "SELF_TEST=1"
set "LOG_FILE=%TEMP%\run_ch_kanban_startup.log"

echo [%DATE% %TIME%] start SELF_TEST=%SELF_TEST% > "%LOG_FILE%"

set "CONDA_CMD="
if defined CONDA_EXE (
    if exist "%CONDA_EXE%" (
        set "CONDA_CMD=%CONDA_EXE%"
    )
)

rem Prefer conda.exe on PATH for robust non-interactive execution.
if not defined CONDA_CMD (
    for /f "delims=" %%I in ('where conda.exe 2^>nul') do (
        if not defined CONDA_CMD set "CONDA_CMD=%%~fI"
    )
)

if not defined CONDA_CMD if exist "%USERPROFILE%\miniconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\miniconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\anaconda3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\mambaforge\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\mambaforge\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%USERPROFILE%\miniforge3\Scripts\conda.exe" set "CONDA_CMD=%USERPROFILE%\miniforge3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%ProgramData%\anaconda3\Scripts\conda.exe" set "CONDA_CMD=%ProgramData%\anaconda3\Scripts\conda.exe"
if not defined CONDA_CMD if exist "%ProgramData%\miniconda3\Scripts\conda.exe" set "CONDA_CMD=%ProgramData%\miniconda3\Scripts\conda.exe"

if not defined CONDA_CMD (
    echo [%DATE% %TIME%] ERROR: conda executable not found. >> "%LOG_FILE%"
    echo [ERROR] conda executable was not found.
    echo         Please install Miniconda/Anaconda, or set CONDA_EXE, or ensure "where conda.exe" works.
    echo         Log: %LOG_FILE%
    pause
    exit /b 1
)

echo [%DATE% %TIME%] CONDA_CMD=%CONDA_CMD% >> "%LOG_FILE%"
call "%CONDA_CMD%" run -n DIG_new python -c "import sys; print(sys.executable)" >nul 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR: conda environment DIG_new unavailable. >> "%LOG_FILE%"
    echo [ERROR] Failed to access conda environment: DIG_new
    echo         Check that the environment exists and Python runs with conda run.
    echo         Log: %LOG_FILE%
    pause
    exit /b 1
)

if "%SELF_TEST%"=="1" (
    call "%CONDA_CMD%" run -n DIG_new python -V >nul 2>&1
    if errorlevel 1 (
        echo [%DATE% %TIME%] ERROR: self-test python run failed. >> "%LOG_FILE%"
        echo [ERROR] self-test failed.
        echo         Log: %LOG_FILE%
        exit /b 1
    )
    echo [%DATE% %TIME%] self-test success. >> "%LOG_FILE%"
    echo [OK] self-test passed. conda + DIG_new + python are available.
    echo      Log: %LOG_FILE%
    exit /b 0
)

call "%CONDA_CMD%" run -n DIG_new python -m src.app.gui
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Application exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
