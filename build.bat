@echo off
setlocal
set VERSION=v1.1.0
set APP_NAME=Spotify LRC Maker
set DIST_APP_DIR=dist

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
    if errorlevel 1 (
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
  --exclude-module=PySide6.Qt3DAnimation ^
  --exclude-module=PySide6.Qt3DCore ^
  --exclude-module=PySide6.Qt3DExtras ^
  --exclude-module=PySide6.Qt3DInput ^
  --exclude-module=PySide6.Qt3DLogic ^
  --exclude-module=PySide6.Qt3DRender ^
  --exclude-module=PySide6.QtBluetooth ^
  --exclude-module=PySide6.QtCharts ^
  --exclude-module=PySide6.QtDataVisualization ^
  --exclude-module=PySide6.QtDesigner ^
  --exclude-module=PySide6.QtGraphs ^
  --exclude-module=PySide6.QtHelp ^
  --exclude-module=PySide6.QtHttpServer ^
  --exclude-module=PySide6.QtLocation ^
  --exclude-module=PySide6.QtMultimedia ^
  --exclude-module=PySide6.QtMultimediaWidgets ^
  --exclude-module=PySide6.QtNetworkAuth ^
  --exclude-module=PySide6.QtNfc ^
  --exclude-module=PySide6.QtPdf ^
  --exclude-module=PySide6.QtPdfWidgets ^
  --exclude-module=PySide6.QtPositioning ^
  --exclude-module=PySide6.QtPrintSupport ^
  --exclude-module=PySide6.QtQml ^
  --exclude-module=PySide6.QtQuick ^
  --exclude-module=PySide6.QtQuick3D ^
  --exclude-module=PySide6.QtQuickControls2 ^
  --exclude-module=PySide6.QtQuickWidgets ^
  --exclude-module=PySide6.QtRemoteObjects ^
  --exclude-module=PySide6.QtScxml ^
  --exclude-module=PySide6.QtSensors ^
  --exclude-module=PySide6.QtSerialBus ^
  --exclude-module=PySide6.QtSerialPort ^
  --exclude-module=PySide6.QtSpatialAudio ^
  --exclude-module=PySide6.QtSql ^
  --exclude-module=PySide6.QtStateMachine ^
  --exclude-module=PySide6.QtSvg ^
  --exclude-module=PySide6.QtSvgWidgets ^
  --exclude-module=PySide6.QtTest ^
  --exclude-module=PySide6.QtTextToSpeech ^
  --exclude-module=PySide6.QtUiTools ^
  --exclude-module=PySide6.QtWebChannel ^
  --exclude-module=PySide6.QtWebEngineCore ^
  --exclude-module=PySide6.QtWebEngineQuick ^
  --exclude-module=PySide6.QtWebEngineWidgets ^
  --exclude-module=PySide6.QtWebSockets ^
  --exclude-module=PySide6.QtWebView ^
  --exclude-module=PySide6.QtXml ^
  main.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo ERROR: Build failed
    echo ========================================
    pause
    exit /b 1
)

echo Copying runtime assets...
copy /y icon.ico "%DIST_APP_DIR%\icon.ico" >nul
if errorlevel 1 (
    echo.
    echo ========================================
    echo ERROR: Failed to copy icon.ico
    echo ========================================
    pause
    exit /b 1
)

xcopy /e /i /y "images" "%DIST_APP_DIR%\images" >nul
if errorlevel 1 (
    echo.
    echo ========================================
    echo ERROR: Failed to copy images
    echo ========================================
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build complete: %APP_NAME% %VERSION%
echo Output: %DIST_APP_DIR%\Spotify LRC Maker.exe
echo Icon: %DIST_APP_DIR%\icon.ico
echo Images: %DIST_APP_DIR%\images
echo ========================================
echo.
pause
