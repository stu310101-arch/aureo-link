@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-server.txt
if not defined AUREO_ENROLL_KEY (
 echo Please set AUREO_ENROLL_KEY before running.
 pause
 exit /b 1
)
if not defined AUREO_PUBLIC_URL set "AUREO_PUBLIC_URL=http://localhost:8787"
.venv\Scripts\python.exe -m server.app
