# Build a standalone Windows .exe with PyInstaller.
#   PS> .\build.ps1
# Output: dist\TimeScout.exe
$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

$iconArg = @()
if (Test-Path "icon.ico") { $iconArg = @("--icon", "icon.ico") }

pyinstaller --noconfirm --clean --onefile --windowed `
    --name TimeScout `
    @iconArg `
    timescout.py

Write-Host ""
Write-Host "Built: dist\TimeScout.exe" -ForegroundColor Green
