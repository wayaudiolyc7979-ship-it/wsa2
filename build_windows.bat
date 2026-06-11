@echo off
REM ============================================================
REM  WSA2 Windows 빌드 — Windows PC 에서 실행 (Mac에서는 불가)
REM  사전: Python 3.9~3.12 설치 (python.org). 그 후 이 파일 더블클릭 또는
REM        명령프롬프트에서: build_windows.bat
REM ============================================================
echo === WSA2 Windows 빌드 ===

python --version
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다. https://python.org 에서 설치하세요.
    pause
    exit /b 1
)

echo 의존성 설치 중...
python -m pip install --upgrade pip
python -m pip install PyQt5 numpy scipy sounddevice soundfile pyinstaller

echo PyInstaller 빌드 중...
python -m PyInstaller WSA2_Windows.spec --clean --noconfirm

echo.
echo === 빌드 완료 ===
echo 산출물: dist\WSA2.exe
echo (미서명이라 첫 실행 시 SmartScreen 경고 - "추가 정보 > 실행" 클릭)
pause
