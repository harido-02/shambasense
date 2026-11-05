@echo off
rem ShambaSense demo launcher for Windows.
rem   run_demo.bat         open ShambaSense on this computer
rem   run_demo.bat phone   also let phones on the same Wi-Fi open it
rem First run: finds or installs Python 3.12, creates a virtual environment, installs
rem packages, loads SYNTHETIC demo data and trains the model (5-10 minutes).
rem Later runs start in seconds.
cd /d "%~dp0"
title ShambaSense
set PYTHONUTF8=1
set DATABASE_URL=sqlite:///data/demo.db
set SHAMBA_DEMO=1
set HOST=127.0.0.1
if /i "%~1"=="phone" set HOST=0.0.0.0

call :find_python
if not defined PY (
  echo Python 3.10 or newer was not found on this computer.
  where winget >nul 2>nul
  if errorlevel 1 goto :manual_python
  echo Installing Python 3.12 with winget. This takes a minute or two...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  call :find_python
)
if not defined PY goto :manual_python
echo Using Python: %PY%

if not exist ".venv\Scripts\python.exe" (
  echo Creating a virtual environment...
  "%PY%" -m venv .venv
  if errorlevel 1 goto :failed
)
set "VPY=%~dp0.venv\Scripts\python.exe"

if not exist ".venv\installed-v2.txt" (
  echo Installing packages. This takes a few minutes the first time...
  "%VPY%" -m pip install --upgrade pip
  "%VPY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
  echo done> ".venv\installed-v2.txt"
)

if not exist "data\demo.db" (
  echo Loading SYNTHETIC demo data...
  "%VPY%" -m shambasense.cli ingest-sample
  if errorlevel 1 goto :failed
)
if not exist "models\yield_model.joblib" (
  echo.
  echo Training the model. This takes about 5 minutes the first time; keep this window open.
  "%VPY%" -m shambasense.cli train
  if errorlevel 1 goto :failed
)

echo.
echo ============================================================
echo  ShambaSense is starting: http://127.0.0.1:8000  (opens in your browser)
echo  Admin dashboard:         http://127.0.0.1:8000/admin
if /i "%~1"=="phone" call :show_phone_address
echo  Keep this window open while you use it. Close it to stop.
echo ============================================================
start "" cmd /c "timeout /t 6 >nul & start http://127.0.0.1:8000"
"%VPY%" -m shambasense.cli serve --host %HOST% --port 8000
pause
exit /b 0


:show_phone_address
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1).IPAddress"`) do set LANIP=%%I
if defined LANIP (
  echo  On your phone, same Wi-Fi: http://%LANIP%:8000
) else (
  echo  On your phone, same Wi-Fi: http://THIS-LAPTOP-IP:8000  ^(find it with ipconfig^)
)
echo  If Windows asks whether to allow Python on networks, choose Allow on Private networks.
exit /b 0


:find_python
set "PY="
for %%P in (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  "%ProgramFiles%\Python312\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python311\python.exe"
  "%USERPROFILE%\anaconda3\python.exe"
  "%USERPROFILE%\miniconda3\python.exe"
  "%LOCALAPPDATA%\anaconda3\python.exe"
  "%ProgramData%\anaconda3\python.exe"
) do (
  if not defined PY if exist %%P (
    %%P -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=%%~P"
  )
)
if defined PY exit /b 0
for %%C in (py python) do (
  if not defined PY (
    %%C -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && for /f "delims=" %%E in ('%%C -c "import sys; print(sys.executable)"') do set "PY=%%E"
  )
)
exit /b 0


:manual_python
echo.
echo Could not install Python automatically.
echo Please install Python 3.12 from the page that is opening now.
echo On the first installer screen tick "Add python.exe to PATH", then run this file again.
start "" https://www.python.org/downloads/windows/
pause
exit /b 1


:failed
echo.
echo Something went wrong. Copy the last lines above and send them to Claude.
pause
exit /b 1
