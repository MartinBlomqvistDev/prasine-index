@echo off
cd /d C:\prasine-index
.venv\Scripts\python.exe scripts\refresh_eutl.py >> logs\refresh_eutl.log 2>&1
