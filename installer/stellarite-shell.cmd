@echo off
rem Stellarite command prompt: the bundled Python on PATH, plus short commands
rem for the wallets and miners. Opened from the Start menu shortcut.
set "APP=%~dp0"
set "PATH=%APP%python;%APP%python\Scripts;%PATH%"
title STELLARITE // COMMAND DECK
color 0C
doskey plsr-wallet=python "%APP%launcher.py" script "%APP%node\wallet.py" $*
doskey plsr-miner=python "%APP%launcher.py" script "%APP%node\miner.py" $*
doskey nblt-wallet=python "%APP%launcher.py" script "%APP%nebulite\wallet.py" $*
doskey nblt-miner=python "%APP%launcher.py" script "%APP%nebulite\miner.py" $*
echo.
echo   [ STELLARITE // COMMAND DECK ]
echo.
echo   plsr-wallet new ^| balance ^| send ^<address^> ^<amount^> ^| claim ^<NAME^>
echo   nblt-wallet new ^| balance ^| send ^<address^> ^<amount^> ^| claim ^<NAME^>
echo   plsr-miner --address plsr...      nblt-miner --address nblt...
echo.
echo   Working folder: %USERPROFILE%\Stellarite
echo   Back up any key you create. The phone app's wallet is the recommended one.
echo.
if not exist "%USERPROFILE%\Stellarite" mkdir "%USERPROFILE%\Stellarite"
cd /d "%USERPROFILE%\Stellarite"
prompt $E[38;2;220;20;60mSTELLARITE$E[0m $E[38;2;255;176;0m$P$E[0m$G
