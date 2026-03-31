@echo off
cd /d "%~dp0"
echo Running Warby Parker Scraper using venv...
venv\Scripts\python.exe scraper.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Scraper encountered an error.
    pause
) else (
    echo.
    echo Scraper finished successfully.
)
