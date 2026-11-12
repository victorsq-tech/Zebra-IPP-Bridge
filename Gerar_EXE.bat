@echo off
setlocal
pushd "%~dp0" || exit /b 1
call :build
set "BUILD_RESULT=%ERRORLEVEL%"
popd
if not "%BUILD_RESULT%"=="0" echo Build interrompido. Consulte a mensagem acima.
if /i not "%~1"=="--no-pause" pause
exit /b %BUILD_RESULT%

:build
if not exist "zebra_ipp_manager.py" (
    echo Extraia todo o ZIP antes de executar este arquivo.
    exit /b 1
)

set "PYTHON=py -3"
where py.exe >nul 2>&1
if errorlevel 1 set "PYTHON=python"

%PYTHON% -c "import sys; sys.exit(sys.version_info < (3, 10))"
if errorlevel 1 (
    echo Instale o Python 3.10 ou superior para Windows com Tcl/Tk.
    exit /b 1
)

if not exist ".build-venv\Scripts\python.exe" (
    %PYTHON% -m venv ".build-venv" || exit /b 1
)
set "BUILD_PYTHON=.build-venv\Scripts\python.exe"
"%BUILD_PYTHON%" -c "import tkinter; root = tkinter.Tk(); root.destroy()"
if errorlevel 1 (
    echo Tcl/Tk indisponivel. Repare a instalacao do Python e recrie .build-venv.
    exit /b 1
)

"%BUILD_PYTHON%" -m pip install PyInstaller || exit /b 1
"%BUILD_PYTHON%" -m PyInstaller --noconfirm --onefile --windowed --name ZebraIPPManager --distpath dist --workpath build --specpath build zebra_ipp_manager.py || exit /b 1
if not exist "dist\ZebraIPPManager.exe" exit /b 1
echo Executavel gerado em "%CD%\dist\ZebraIPPManager.exe"
exit /b 0
