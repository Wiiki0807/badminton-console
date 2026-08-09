@echo off
setlocal
cd /d "%~dp0"
set "PORT=4173"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_EXE=py"
) else (
  set "PYTHON_EXE=python"
)
start "Badminton Live Server" /min "%PYTHON_EXE%" "%~dp0server.py" --port %PORT%
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:%PORT%/?view=courts"
endlocal
