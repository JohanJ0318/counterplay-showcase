@echo off
REM Checks the whole app end to end. Pass a URL to test a deployed site:
REM   smoke-test.bat https://your-domain
cd /d "%~dp0"
if "%~1"=="" (python -m app.smoke) else (python -m app.smoke --url %1)
pause
