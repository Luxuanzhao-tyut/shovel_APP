$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating Python 3.11 virtual environment..."
    & py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv with Python 3.11." }
}
$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Write-Host "Installing/updating dependencies..."
& $Py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $Py -m pip install -r requirements-ui.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $Py build_app.py
if ($LASTEXITCODE -ne 0) { throw "Application build failed." }
