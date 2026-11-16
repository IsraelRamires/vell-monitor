@echo off
chcp 65001 >nul
title MONITOR TOKEN VELL
cd /d "%~dp0"
echo Iniciando o monitor do VELL...
echo O painel abre sozinho no navegador em http://localhost:8765
echo Deixe esta janela aberta. Para parar, feche a janela.
echo.
python servidor.py
pause
