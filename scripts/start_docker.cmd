@echo off
chcp 65001 >nul
cd /d "%~dp0.."
docker compose up --build -d
if errorlevel 1 (
  echo.
  echo 启动失败，请把上面的错误完整发给 Codex。
  pause
  exit /b 1
)
docker compose ps
echo.
echo 启动成功后访问 http://127.0.0.1:8501
pause
