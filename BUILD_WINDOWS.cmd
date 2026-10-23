@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)
%PYTHON% -m venv .venv
if errorlevel 1 goto failed
set "BUILD_REQUIREMENTS=requirements-dev.txt"
if exist requirements-build-lock.txt set "BUILD_REQUIREMENTS=requirements-build-lock.txt"
.venv\Scripts\python.exe -m pip install -r "%BUILD_REQUIREMENTS%" "pyinstaller>=6,<7"
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 goto failed
where node >nul 2>nul
if errorlevel 1 goto skip_js
node --check pwa\app.js
if errorlevel 1 goto failed
node tests\test_pwa.cjs
if errorlevel 1 goto failed
:skip_js
.venv\Scripts\python.exe FETCH_TUNNEL.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe PREPARE_LICENSES.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onefile --name AureoLink --icon pwa/icons/aureo-link.ico --version-file desktop/version-info.txt --paths . --add-data "pwa;pwa" --add-binary "tools/cloudflared.exe;tools" --add-data "tools/LICENSE-cloudflared.txt;tools" --add-data "tools/cloudflared-release.json;tools" --add-data "THIRD_PARTY_NOTICES.txt;." --add-data "licenses;licenses" desktop\app.py
if errorlevel 1 goto failed
echo.
echo Success: dist\AureoLink.exe (self-contained)
if not "%~1"=="--no-pause" pause
exit /b 0
:failed
echo Build failed. Check errors above.
if not "%~1"=="--no-pause" pause
exit /b 1
