@echo off
setlocal

echo ============================================================
echo   Build gui.exe tu gui.py
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay python trong PATH.
    echo       Cai Python (python.org^), nho tick "Add python.exe to PATH" khi cai.
    pause
    exit /b 1
)

if not exist gui.py (
    echo [LOI] Khong thay gui.py trong thu muc hien tai.
    echo       Chay file build_exe.bat nay TU thu muc chua gui.py.
    pause
    exit /b 1
)

echo [1/3] Cai/cap nhat PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo [LOI] Cai PyInstaller that bai. Kiem tra ket noi mang / pip.
    pause
    exit /b 1
)

echo.
echo [2/3] Dang build gui.exe (co the mat 1-2 phut)...
python -m PyInstaller --onefile --windowed --name gui --distpath . --workpath build --specpath build gui.py
if errorlevel 1 (
    echo [LOI] PyInstaller build that bai. Xem log loi o tren.
    pause
    exit /b 1
)

if not exist gui.exe (
    echo [LOI] Build xong nhung khong thay gui.exe. Kiem tra lai log o tren.
    pause
    exit /b 1
)

echo.
echo [3/3] Don dep file build tam (build\, gui.spec)...
rmdir /s /q build 2>nul
del /q gui.spec 2>nul

echo.
echo ============================================================
echo   XONG! gui.exe da nam cung thu muc voi cac file .py.
echo   Tu gio chi can double-click gui.exe de mo chuong trinh --
echo   khong can mo cmd, khong can go lenh python nua.
echo.
echo   Luu y: Windows Defender / diet virus doi khi bao nham
echo   voi file .exe dong goi bang PyInstaller (do cach --onefile
echo   tu giai nen luc chay). Neu bi chan, chon "Cho phep" / them
echo   ngoai le cho gui.exe.
echo ============================================================
pause