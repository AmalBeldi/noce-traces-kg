@echo off
chcp 65001 > nul
cd /d "%~dp0"
cls
py demo.py --seminaire
if errorlevel 1 pause
