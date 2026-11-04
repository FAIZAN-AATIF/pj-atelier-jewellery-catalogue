@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo       PJ JEWELLERY CATALOGUE
echo ============================================

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher was not found. Install Python 3.10+ and enable Add Python to PATH.
  pause
  exit /b 1
)

if not exist "venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3 -m venv venv
  if errorlevel 1 (
    echo Could not create virtual environment.
    pause
    exit /b 1
  )
)

call "venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto failed
python -m pip install -r requirements.txt
if errorlevel 1 goto failed

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example.
  echo Configure your admin login in the .env file.
  echo Change APP_SECRET_KEY and ADMIN_PASSWORD in .env before sharing/deploying.
)

echo Starting PJ Jewellery Catalogue...
echo Storefront: http://127.0.0.1:8000
echo Admin:      http://127.0.0.1:8000/admin
echo API docs:   http://127.0.0.1:8000/docs
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto end

:failed
echo.
echo Setup failed. Check the error above and try again.
pause
exit /b 1

:end
pause
