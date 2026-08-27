@echo off
setlocal EnableExtensions
title M-LLM Universal Installer

set "ENTRY=%~dp0installer\Start-UniversalInstaller.ps1"
if not exist "%ENTRY%" (
  echo [FATAL] Universal installer entrypoint is missing:
  echo         %ENTRY%
  echo.
  pause
  exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ENTRY%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] Universal installer exited with RC=%RC%
  echo Press any key to close.
  pause >nul
)
exit /b %RC%
