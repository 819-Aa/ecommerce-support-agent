@echo off
chcp 65001 >nul
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\verify_docker.py
if errorlevel 1 pause
