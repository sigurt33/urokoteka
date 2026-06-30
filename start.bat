@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запуск сервера записей уроков...
echo Откройте в браузере: http://127.0.0.1:8765
start "" http://127.0.0.1:8765
where py >nul 2>nul && (py server.py) || (python server.py)
echo.
echo Сервер остановлен. Можно закрыть окно.
pause
