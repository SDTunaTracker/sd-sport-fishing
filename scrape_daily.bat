@echo off
cd /d "C:\Users\Jenelle\Projects\sd-sport-fishing"
.venv\Scripts\python.exe -u -m src.main >> logs\scrape_daily.log 2>&1
