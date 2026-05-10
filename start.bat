@echo off
REM One-click launcher for the SME Loan Triage demo.
REM Opens two PowerShell windows: one for the mock credit API,
REM one for the Streamlit UI. Streamlit auto-opens the browser.
REM
REM Usage:
REM   - Double-click this file in Explorer, OR
REM   - Run `.\start.bat` in any terminal.

cd /d %~dp0

start "SME Demo - Credit API"   powershell -NoExit -Command "python credit_api.py"
timeout /t 2 /nobreak >nul
start "SME Demo - Streamlit UI" powershell -NoExit -Command "python -m streamlit run app.py"

echo.
echo Both services launching in separate windows.
echo Browser will open automatically at http://localhost:8501
echo Close both PowerShell windows when you are done.
echo.
