@echo off
rem Starts the Nebulite node on this computer (Windows). Double-click to run.
rem First run: sets up Python packages in nebulite\.venv and creates your wallet.
cd /d "%~dp0nebulite"

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
  echo Creating your Nebulite wallet. Back up nebulite\wallet.json: it holds your coins' key.
  python wallet.py new
)
echo.
echo Your Nebulite address (paste into the app's WALLET_ADDR):
python wallet.py address
echo.
echo When Windows asks, allow Python on PRIVATE networks so your phone can connect.
python node.py --port 5001
pause
