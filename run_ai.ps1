$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    throw 'First run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r services/ai/requirements.txt'
}
& .\.venv\Scripts\python.exe -m services.ai.main
