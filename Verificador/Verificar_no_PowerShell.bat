@echo off
cd /d "%~dp0"
py -3 verificador_zebra.py --ip 192.168.10.76 --port 631 --output relatorios
pause
