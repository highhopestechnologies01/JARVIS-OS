@echo off
echo === JARVIS Meta Ads Scraper — Install ===

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

:: Install dependencies
echo Installing Python packages...
pip install -r requirements.txt

:: Install Playwright browsers (only Chromium needed)
echo Installing Playwright Chromium...
playwright install chromium

:: Copy config if not exists
if not exist config.json (
    copy config.example.json config.json
    echo.
    echo IMPORTANT: Edit config.json with your settings:
    echo   - hermes_url: your VPS IP + port 8001
    echo   - scraper_token: match SCRAPER_TOKEN in VPS .env
    echo   - rdp_host: "RDP-1" or "RDP-2"
    echo.
)

echo.
echo Install complete. Next steps:
echo 1. Edit config.json
echo 2. Run: python scraper.py  (to test manually)
echo 3. Set up Windows Task Scheduler using schedule.bat
pause
