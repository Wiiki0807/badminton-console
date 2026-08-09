@echo off
setlocal
pushd "%~dp0"

set "PYTHON_EXE=C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PYTHON_EXE%" goto python_found

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  goto python_found
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python"
  goto python_found
)

echo [ERROR] Python was not found.
echo Please install Python 3.11 or later and run this file again.
goto finished

:python_found
echo [1/4] Installing video dependencies...
"%PYTHON_EXE%" -m pip install --quiet edge-tts playwright imageio-ffmpeg mutagen
if errorlevel 1 goto failed

echo [2/4] Installing Chromium for screenshots...
"%PYTHON_EXE%" -m playwright install chromium
if errorlevel 1 goto failed

echo [3/4] Generating narration and screenshots...
"%PYTHON_EXE%" "make_demo_video.py"
if errorlevel 1 goto failed

echo [4/4] Video completed.
for %%F in ("..\*.mp4") do start "" "%%~fF"
goto finished

:failed
echo.
echo [ERROR] Video generation failed. Please copy the error above.

:finished
echo.
pause
popd
endlocal
