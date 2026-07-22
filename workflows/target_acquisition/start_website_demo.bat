@echo off
rem =========================================================================
rem Start the ZMART target-acquisition website in DEMO mode.
rem
rem Double-click to try the whole workflow on a simulated microscope and
rem sample — nothing real moves, no Leica needed. Great for learning the
rem flow before a real session. Uses the same per-machine settings file
rem (start_website.local.bat) as start_website.bat, if one exists.
rem =========================================================================

setlocal
cd /d "%~dp0"

set "PYTHON=python"
set "ZMART_ARGS="
if exist "start_website.local.bat" call "start_website.local.bat"

"%PYTHON%" run_webapp.py --open --demo %*

if errorlevel 1 pause
endlocal
