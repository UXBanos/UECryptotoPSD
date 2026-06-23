@echo off
REM ============================================================
REM  build.bat  -  Build CryptomatteExtractor.exe on Windows
REM  Uses Python 3.13 (via "py -3.13"); OpenEXR has no wheels
REM  for Python 3.14+.
REM ============================================================

cd /d "%~dp0"

echo.
echo === [1/5] Looking for Python 3.13 / 3.12 / 3.11 ===
set "PY="
py -3.13 --version >nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3.11 --version >nul 2>&1 && set "PY=py -3.11"
if not defined PY goto NOPY

echo Using: %PY%
%PY% --version

echo.
echo === [2/5] Creating virtual environment ===
if exist ".venv" rmdir /s /q ".venv"
%PY% -m venv .venv
if errorlevel 1 goto FAIL
call ".venv\Scripts\activate.bat"

echo.
echo === [3/5] pip + numpy + PySide6 ===
python -m pip install --upgrade pip
python -m pip install "numpy>=1.24" "PySide6>=6.5"
if errorlevel 1 goto FAIL

echo.
echo === [4/5] OpenEXR (prebuilt wheel only) ===
python -m pip install --only-binary=:all: OpenEXR
if errorlevel 1 goto FAILEXR

echo.
echo === [5/5] Building the executable with PyInstaller ===
python -m pip install pyinstaller
if errorlevel 1 goto FAIL
pyinstaller --noconfirm --onefile --windowed --name CryptomatteExtractor crypto_extractor.py
if errorlevel 1 goto FAIL

echo.
echo === DONE ===
echo Your executable is at:  "%~dp0dist\CryptomatteExtractor.exe"
echo You can move it anywhere and run it with a double click.
goto END

:NOPY
echo ============================================================
echo  Could not find Python 3.11, 3.12 or 3.13.
echo  Python 3.14 will not work: OpenEXR has no wheel for it.
echo.
echo  FIX:
echo   1. Install 64 bit Python 3.13 from:
echo      https://www.python.org/downloads/release/python-3137/
echo      Tick the "py launcher" option in the installer.
echo   2. Run this build.bat again.
echo ============================================================
goto END

:FAILEXR
echo ============================================================
echo  Could not install OpenEXR from a wheel.
echo  Make sure the Python you are using is 64 bit.
echo ============================================================
goto END

:FAIL
echo.
echo ERROR: the process failed at the step above. Check the messages.

:END
echo.
pause
