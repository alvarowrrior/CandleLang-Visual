@echo off
cd /d "%~dp0"
py -m candlelab vela
if errorlevel 1 pause
