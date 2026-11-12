@echo off
cd /d "%~dp0"
py -3 verificador_zebra.py --gui
if errorlevel 1 (
  echo.
  echo Nao foi possivel abrir a interface grafica.
  pause
)
