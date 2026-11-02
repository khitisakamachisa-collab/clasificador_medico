@echo off
title Clasificador Medico

echo Iniciando API FastAPI...
start "API FastAPI" cmd /k ".\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000"

timeout /t 3 /nobreak > nul

echo Iniciando servidor web...
start "Frontend" cmd /k ".\.venv\Scripts\python.exe -m http.server 3000"

timeout /t 2 /nobreak > nul

echo Abriendo navegador...
start http://localhost:3000

exit