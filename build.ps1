# Build a standalone Windows .exe with PyInstaller.
#   PS> .\build.ps1
# Output: dist\ClaudeUsageWidget.exe
$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

$iconArg = @()
if (Test-Path "icon.ico") { $iconArg = @("--icon", "icon.ico") }

pyinstaller --noconfirm --clean --onefile --windowed `
    --name ClaudeUsageWidget `
    @iconArg `
    claude_usage_widget.py

Write-Host ""
Write-Host "Built: dist\ClaudeUsageWidget.exe" -ForegroundColor Green
