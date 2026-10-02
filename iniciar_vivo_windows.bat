@echo off
cd /d "%~dp0"
py -m candlelab vela vivo
if errorlevel 1 pause
