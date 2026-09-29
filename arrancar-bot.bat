@echo off
title askhub - bot de #preguntar
cd /d "%~dp0"

py -3 askhub.py bot
if errorlevel 9009 python askhub.py bot

echo.
echo El bot se ha parado. Cierra esta ventana o pulsa una tecla.
pause >nul
