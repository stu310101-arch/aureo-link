@echo off
setlocal
cd /d "%~dp0"
call BUILD_WINDOWS.cmd --no-pause
if errorlevel 1 goto failed
.venv\Scripts\python.exe FETCH_INSTALLER_TOOL.py
if errorlevel 1 goto failed
".build-tools\inno-setup-6.7.3\ISCC.exe" installer\AureoLink.iss
if errorlevel 1 goto failed
echo.
echo Success: dist\installer\AmosLink-Setup.exe
if not "%~1"=="--no-pause" pause
exit /b 0
:failed
echo Installer build failed. Check errors above.
if not "%~1"=="--no-pause" pause
exit /b 1
