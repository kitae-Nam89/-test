@echo off
REM === 프리랜서 TEST 서버 실행 스크립트 ===

REM 1) 프로젝트 폴더로 이동
cd /d "C:\Users\USER\Desktop\프리랜서TEST"

REM 2) 가상환경 활성화
call venv\Scripts\activate.bat

REM 3) 서버 실행 (백그라운드 유지)
start "" python server.py

REM 잠깐 대기 (서버가 켜질 시간)
timeout /t 2 >nul

REM 4) 브라우저 자동 실행
start "" "http://127.0.0.1:5000/"
start "" "http://127.0.0.1:5000/admin_login"

REM 5) 창 유지
pause
