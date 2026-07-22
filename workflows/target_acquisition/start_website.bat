@echo off
rem =========================================================================
rem Start the ZMART target-acquisition website (live microscope).
rem
rem Double-click this file on the microscope PC. It starts the local server
rem and opens the page in your browser. Keep the window that appears open
rem during the run; press Ctrl+C in it (after Disconnect in the website)
rem to stop.
rem
rem Machine-specific choices (which Python to use, where the analysis repo
rem lives) do NOT belong in this file — they differ per microscope PC.
rem Put them in a file named  start_website.local.bat  next to this one.
rem That file is yours: it is listed in .gitignore, so updating the
rem repository never overwrites it. Example content:
rem
rem     set "PYTHON=C:\ProgramData\MinicondaZMB\envs\zmart-microscopy\python.exe"
rem     set "ZMART_ARGS=--analysis-repo C:\path\to\smart-analysis"
rem
rem Without a local file, the Python on your PATH is used with no extra
rem arguments (which is enough for the demo, but a live session needs
rem --analysis-repo).
rem =========================================================================

setlocal
cd /d "%~dp0"

set "PYTHON=python"
set "ZMART_ARGS="
if exist "start_website.local.bat" call "start_website.local.bat"

"%PYTHON%" run_webapp.py --open %ZMART_ARGS% %*

rem Keep the window open if Python exited with an error, so the message
rem can actually be read instead of vanishing with the window.
if errorlevel 1 pause
endlocal
