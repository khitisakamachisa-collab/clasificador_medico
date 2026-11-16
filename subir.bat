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
git commit -m "docs: Agregar metodologia de tesis con pipeline anti-alucinaciones, evolucion NLP v1-v4 y arquitectura hibrida"

echo ==============================
echo 4. Subiendo a GitHub...
echo ==============================
git push origin main

echo ==============================
echo Proceso completado.
pause
