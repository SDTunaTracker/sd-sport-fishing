@echo off
cd /d "C:\Users\Jenelle\Projects\sd-sport-fishing"
.venv\Scripts\python.exe -u -m src.main --hourly >> logs\scrape_hourly.log 2>&1
