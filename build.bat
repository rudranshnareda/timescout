@echo off
REM Build a standalone Windows .exe with PyInstaller.
REM   build.bat
REM Output: dist\TimeScout.exe
setlocal

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :err

set ICON=
if exist icon.ico set ICON=--icon icon.ico

pyinstaller --noconfirm --clean --onefile --windowed --name TimeScout %ICON% timescout.py
if errorlevel 1 goto :err

echo.
echo Built: dist\TimeScout.exe
goto :eof

:err
echo Build failed.
exit /b 1
