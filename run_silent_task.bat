@echo off
cd /d "%~dp0"
echo Running V-DPWR-EPR Updater with zero UAC prompts...
schtasks /run /tn "V_DPWR_Updater"
