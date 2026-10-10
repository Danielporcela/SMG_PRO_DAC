$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host '========================================'
Write-Host '      SGMF PRO - INICIALIZACAO'
Write-Host '========================================'

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host '[1/3] Criando ambiente virtual...'
    py -m venv .venv
}
else {
    Write-Host '[1/3] Ambiente virtual encontrado.'
}

Write-Host '[2/3] Verificando dependencias...'
& .venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host '[3/3] Iniciando servidor SGMF...'
Write-Host 'Acesse: http://127.0.0.1:5000'
& .venv\Scripts\python.exe app.py
