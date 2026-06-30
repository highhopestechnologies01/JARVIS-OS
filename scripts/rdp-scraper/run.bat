@echo off
:: JARVIS Meta Ads Scraper — run script
:: Called by Windows Task Scheduler every 5 minutes

cd /d "%~dp0"
python scraper.py >> scraper.log 2>&1
