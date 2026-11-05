@echo off
rem Creates (or promotes) an administrator account for the dashboard at /admin.
rem Run run_demo.bat once first, so the environment exists.
cd /d "%~dp0"
set PYTHONUTF8=1
set DATABASE_URL=sqlite:///data/demo.db
if not exist ".venv\Scripts\python.exe" (
  echo Run run_demo.bat first, then try again.
  pause
  exit /b 1
)
set /p ADMIN_PHONE=Your mobile number (e.g. 0712345678): 
set /p ADMIN_PIN=Choose a 4-digit PIN: 
".venv\Scripts\python.exe" -m shambasense.cli create-admin --phone "%ADMIN_PHONE%" --pin "%ADMIN_PIN%" --name "Administrator"
echo.
echo Sign in at http://127.0.0.1:8000/admin with that number and PIN (while run_demo.bat is running).
pause
