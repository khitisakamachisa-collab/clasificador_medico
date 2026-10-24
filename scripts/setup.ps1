$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "No existe .venv. Créalo primero con: python -m venv .venv"
}

& $python -m pip install -r (Join-Path $projectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "No se pudieron instalar las dependencias del proyecto."
}

& $python -c "import spacy; spacy.load('es_core_news_sm')" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $python -m spacy download es_core_news_sm
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo descargar es_core_news_sm. Revisa la conexión e inténtalo de nuevo."
    }
}

Write-Output "Entorno preparado."
