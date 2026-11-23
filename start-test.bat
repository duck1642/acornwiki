@echo off
cd /d "%~dp0"
python start_test.py
if errorlevel 1 pause
