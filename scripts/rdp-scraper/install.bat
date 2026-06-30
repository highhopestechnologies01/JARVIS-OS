@echo off
echo === JARVIS Meta Ads Scraper — Install ===

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

:: Install dependencies (no Playwright needed — uses raw CDP websockets)
echo Installing Python packages...
pip install -r requirements.txt

:: Copy config if not exists
if not exist config.json (
    copy config.example.json config.json
    echo.
    echo IMPORTANT: Edit config.json with your settings:
    echo   - hermes_url: your VPS Tailscale IP + port 8001
    echo   - scraper_token: match SCRAPER_TOKEN in VPS .env
    echo   - rdp_host: "RDP-1" or "RDP-2"
    echo.
)

echo.
echo Install complete. Next steps:
echo 1. Install Tailscale: https://tailscale.com/download/windows
echo 2. Log into Tailscale with your account
echo 3. Edit config.json (hermes_url = http://100.73.196.118:8001)
echo 4. Run: python scraper.py  (to test manually)
echo 5. Set up Windows Task Scheduler using schedule.bat
pause
