@echo off
setlocal
pushd "%~dp0" || exit /b 1
call :install
set "RESULT=%ERRORLEVEL%"
popd
if /i not "%~1"=="--no-pause" pause
exit /b %RESULT%

:install
set "ZEBRA_PY=py -3"
where py.exe >nul 2>&1
if errorlevel 1 set "ZEBRA_PY=python"
%ZEBRA_PY% -c "import sys, tkinter; sys.exit(sys.version_info < (3, 10))"
if errorlevel 1 (
    echo Instale Python 3.10 ou superior com Tcl/Tk.
    exit /b 1
)
for %%F in (ipp_server.py zebra_formatter.py zebra_fast_engine.py print_pdf_zebra.py requirements.txt) do (
    if not exist "%%F" (
        echo Falta %%F. Consulte o README e copie os arquivos originais do projeto.
        exit /b 2
    )
)
if not exist ".venv\Scripts\python.exe" (
    %ZEBRA_PY% -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
".venv\Scripts\python.exe" -m pip check || exit /b 1
".venv\Scripts\python.exe" -m py_compile ipp_server.py zebra_formatter.py zebra_fast_engine.py print_pdf_zebra.py zebra_ipp_manager.py verificador_zebra.py || exit /b 1
".venv\Scripts\python.exe" -u ipp_server.py --help || exit /b 1
echo Instalacao validada. Abra Iniciar_Manager.bat.
exit /b 0
