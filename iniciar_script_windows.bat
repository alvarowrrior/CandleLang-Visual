@echo off
cd /d "%~dp0"
py -m candlelab script
if errorlevel 1 pause
