@echo off
chcp 65001 >nul
cd /d "%~dp0.."
docker compose down
if errorlevel 1 pause
