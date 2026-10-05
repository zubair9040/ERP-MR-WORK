@echo off
rem Try the ERP on a Windows PC (for testing - the real system runs on a cloud server).
cd /d "%~dp0"
title ERP - keep this window open while using it

if not exist "%~dp0wsgi.py" (
  echo.
  echo  PROBLEM: the folder is still inside the ZIP file.
  echo  Right-click ERP-Phase1.zip, choose "Extract All", then open the extracted
  echo  "erp" folder and double-click start-windows.bat from there.
  echo.
  pause
  exit /b
)

set PY=
python -c "import sys" >nul 2>&1 && set PY=python
if not defined PY py -3 -c "import sys" >nul 2>&1 && set PY=py -3
if not defined PY (
  echo.
  echo  PROBLEM: Python is not installed.
  echo  Download Python 3.12 from https://www.python.org/downloads/
  echo  During install, TICK the box "Add python.exe to PATH", then run this file again.
  echo.
  pause
  exit /b
)

echo Installing required parts (first time only, needs internet)...
%PY% -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo  PROBLEM: could not install the required parts. Check the internet connection
  echo  and send a screenshot of this window.
  echo.
  pause
  exit /b
)

if not exist data\erp.sqlite3 (
  choice /c YN /m "Load demo data to try it out"
  if not errorlevel 2 %PY% manage.py demo
)

echo.
echo  ============================================================
echo    ERP is starting. Your browser will open http://localhost:8000
echo    Keep THIS window open. Close it to stop the ERP.
echo  ============================================================
echo.
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8000"
set ERP_DEBUG=1
set ERP_HOST=127.0.0.1
%PY% wsgi.py
echo.
echo  The ERP stopped. If you see an error above, send a screenshot of this window.
pause
