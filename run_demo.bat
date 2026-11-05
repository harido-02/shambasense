@echo off
rem ShambaSense demo launcher for Windows.
rem First run: finds or installs Python 3.12, creates a virtual environment, installs
rem packages, loads SYNTHETIC demo data and trains the model (5-10 minutes).
rem Later runs start in seconds.
cd /d "%~dp0"
title ShambaSense
set PYTHONUTF8=1
set DATABASE_URL=sqlite:///data/demo.db

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

if not exist ".venv\installed.txt" (
  echo Installing packages. This takes a few minutes the first time...
  "%VPY%" -m pip install --upgrade pip
  "%VPY%" -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
  echo done> ".venv\installed.txt"
)

if not exist "data\demo.db" (
  echo Loading SYNTHETIC demo data...
  "%VPY%" -m shambasense.cli ingest-sample
  if errorlevel 1 goto :failed
)
if not exist "models\yield_model.joblib" (
  echo Training the model. About a minute...
  "%VPY%" -m shambasense.cli train
  if errorlevel 1 goto :failed
)

echo.
echo ShambaSense is starting at http://127.0.0.1:8000   API docs: http://127.0.0.1:8000/docs
echo Keep this window open while you use it. Close it to stop ShambaSense.
start "" cmd /c "timeout /t 6 >nul & start http://127.0.0.1:8000"
"%VPY%" -m shambasense.cli serve
pause
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
