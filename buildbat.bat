@echo off
setlocal
set VERSION=v1.0.0
set APP_NAME=Spotify LRC Maker

echo ========================================
echo Building %APP_NAME% %VERSION%...
echo ========================================
echo.

if not exist .venv\Scripts\python.exe (
    echo ERROR: .venv is missing.
    echo Run:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist .venv\Scripts\pyinstaller.exe (
    echo PyInstaller is not installed. Installing it now...
    .venv\Scripts\python.exe -m pip install pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Building executable...
echo.

.venv\Scripts\pyinstaller.exe ^
  --name "Spotify LRC Maker" ^
  --onefile ^
  --windowed ^
  --icon=icon.ico ^
  --add-data "icon.ico;." ^
  --add-data "images;images" ^
  --hidden-import=PySide6.QtCore ^
  --hidden-import=PySide6.QtGui ^
  --hidden-import=PySide6.QtWidgets ^
  --hidden-import=winrt.windows.foundation ^
  --hidden-import=winrt.windows.foundation.collections ^
  --hidden-import=winrt.windows.media.control ^
  --collect-all=PySide6 ^
  --collect-all=winrt ^
  main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================
    echo ERROR: Build failed
    echo ========================================
    pause
    exit /b 1
)

echo Copying icon.ico to dist...
copy /y icon.ico dist\icon.ico >nul

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================
    echo ERROR: Failed to copy icon.ico to dist
    echo ========================================
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build complete: %APP_NAME% %VERSION%
echo Output: dist\Spotify LRC Maker.exe
echo Icon: dist\icon.ico
echo ========================================
echo.
pause
