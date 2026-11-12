@echo off
setlocal
pushd "%~dp0" || exit /b 1
set "ZEBRA_PY=py -3"
where py.exe >nul 2>&1
if errorlevel 1 set "ZEBRA_PY=python"
if exist ".venv\Scripts\python.exe" set "ZEBRA_PY=.venv\Scripts\python.exe"
%ZEBRA_PY% zebra_ipp_manager.py
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" pause
exit /b %RESULT%
