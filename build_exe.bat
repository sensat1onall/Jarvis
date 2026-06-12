@echo off
REM ===========================================================================
REM  JARVIS MARK XL - one-click .exe build (cloud-only)
REM  Produces: dist\JARVIS\JARVIS.exe  (+ runtime resources beside it)
REM  Run from the project root:  build_exe.bat
REM ===========================================================================
setlocal
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo ERROR: %PY% not found. Create the venv first.
    exit /b 1
)

echo [1/3] Building with PyInstaller ^(a few minutes^)...
"%PY%" -m PyInstaller jarvis.spec --noconfirm
if errorlevel 1 ( echo BUILD FAILED & exit /b 1 )

echo [2/3] Copying runtime resources beside the exe...
copy /Y face.png "dist\JARVIS\" >nul
if not exist "dist\JARVIS\core" mkdir "dist\JARVIS\core"
copy /Y "core\prompt.txt" "dist\JARVIS\core\" >nul
if not exist "dist\JARVIS\config" mkdir "dist\JARVIS\config"
if exist "config\api_keys.json" copy /Y "config\api_keys.json" "dist\JARVIS\config\" >nul

echo [3/3] Done.
echo.
echo   Run it:    dist\JARVIS\JARVIS.exe
echo   Share it:  zip the whole  dist\JARVIS  folder
echo.
endlocal
