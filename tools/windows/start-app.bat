@echo off
REM Starts the web app. %~dp0 is this file's own folder, so the working
REM directory is right no matter where the shortcut is launched from --
REM `python -m app` only resolves from the project root.
cd /d "%~dp0..\.."
echo Counterplay running at http://127.0.0.1:8000   (Ctrl+C to stop)
python -m app
pause
