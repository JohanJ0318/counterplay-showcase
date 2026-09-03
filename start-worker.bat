@echo off
REM Parses whatever demos are waiting, then keeps watching for more.
REM Run this alongside start-app.bat: uploading and parsing are separate
REM processes, because a 300MB demo takes minutes and would time out a request.
cd /d "%~dp0"
python -m app.worker
pause
