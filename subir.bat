@echo off
REM Sincronización automática con GitHub para clasificador_medico

REM Cambia al directorio del proyecto
cd /d "D:\clasificador_medico"

echo ==============================
echo 1. Trayendo cambios remotos...
echo ==============================
git pull origin main --allow-unrelated-histories

echo ==============================
echo 2. Preparando archivos locales...
echo ==============================
git add .

echo ==============================
echo 3. Creando commit...
echo ==============================
git commit -m "feat: Modelo NLP masivo v3 con accuracy 77.1%. Diccionario de sinónicos médico implementado. 174 ejemplos de alta calidad entrenados."

echo ==============================
echo 4. Subiendo a GitHub...
echo ==============================
git push origin main

echo ==============================
echo Proceso completado.
pause
