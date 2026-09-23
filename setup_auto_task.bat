@echo off
cd /d "%~dp0"
echo ===============================================================
echo   Setting up Zero-Prompt Elevated Task for V-DPWR-EPR Updater
echo ===============================================================
echo This registers a Windows Scheduled Task configured to run with
echo highest privileges so you will NEVER have to click 'Yes' on UAC.
echo.

set "PYTHON_EXE=%~dp0env\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python.exe"

set "TASK_CMD=\"%PYTHON_EXE%\" \"%~dp0install.py\""

powershell -Command "Start-Process schtasks -ArgumentList '/create /tn \"V_DPWR_Updater\" /tr \"%TASK_CMD%\" /sc once /st 00:00 /rl HIGHEST /f' -Verb RunAs -Wait"

echo.
echo Setup completed!
echo From now on, you can run the updater with ZERO UAC prompts using:
echo    schtasks /run /tn "V_DPWR_Updater"
echo Or by double-clicking 'run_silent_task.bat'
echo ===============================================================
pause
