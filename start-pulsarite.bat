@echo off
rem Starts the Pulsarite node on this computer (Windows). Double-click to run.
rem First run: sets up Python packages in node\.venv and creates your wallet.
cd /d "%~dp0node"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python 3 isn't installed. Get it from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH". Then run this again.
  pause
  exit /b 1
)

if not exist .venv (
  echo First run: setting up Python packages, one minute...
  %PY% -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q --disable-pip-version-check -r requirements.txt

if not exist wallet.json (
  echo.
  echo Creating your Pulsarite wallet. Back up node\wallet.json: it holds your coins' key.
  python wallet.py new
)
echo.
echo Your Pulsarite address (paste into the app's WALLET_ADDR):
python wallet.py address
echo.
echo When Windows asks, allow Python on PRIVATE networks so your phone can connect.
python node.py --port 5000
pause
