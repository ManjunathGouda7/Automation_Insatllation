@echo off
cd /d "%~dp0"
if exist ".\env\Scripts\python.exe" (
    powershell -Command "Start-Process -FilePath '.\env\Scripts\python.exe' -ArgumentList 'install.py' -Verb RunAs"
) else (
    powershell -Command "Start-Process -FilePath 'python' -ArgumentList 'install.py' -Verb RunAs"
)
