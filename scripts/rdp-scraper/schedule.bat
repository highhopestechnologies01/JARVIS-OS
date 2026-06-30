@echo off
:: Creates a Windows Task Scheduler task to run the scraper every 5 minutes.
:: Run this ONCE as Administrator.

set TASK_NAME=JARVIS-MetaAdsScraper
set SCRIPT_DIR=%~dp0
set RUN_BAT=%SCRIPT_DIR%run.bat

echo Creating scheduled task: %TASK_NAME%
echo Script: %RUN_BAT%

schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%RUN_BAT%\"" ^
  /sc minute ^
  /mo 5 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if errorlevel 1 (
    echo ERROR: Failed to create task. Run this script as Administrator.
    pause
    exit /b 1
)

echo.
echo Task created. Scraper will run every 5 minutes.
echo To verify: Open Task Scheduler and look for JARVIS-MetaAdsScraper
echo To run now: schtasks /run /tn "%TASK_NAME%"
echo To remove: schtasks /delete /tn "%TASK_NAME%" /f
pause
