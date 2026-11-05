@echo off
rem ============================================================
rem DevDocs Copilot - one-click dev launcher (double-click me)
rem
rem Runs current source with hot reload; no need to rebuild the exe.
rem   start.bat            start server + open browser
rem   start.bat nobrowser  start server only
rem
rem Chinese messages live in scripts\start_dev.ps1 (ASCII bat avoids
rem cmd codepage issues between UTF-8 and GBK consoles).
rem ============================================================
cd /d "%~dp0"

if "%~1"=="nobrowser" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_dev.ps1" -NoBrowser
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_dev.ps1"
)

if errorlevel 1 pause
