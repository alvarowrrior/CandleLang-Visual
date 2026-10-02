@echo off
cd /d "%~dp0"
py -m candlelab hex
if errorlevel 1 pause
