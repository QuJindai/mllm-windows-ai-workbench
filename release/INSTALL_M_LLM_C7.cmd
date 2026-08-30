@echo off
setlocal EnableExtensions
title M-LLM Workbench C7 Offline Installer

set "ENTRY=%~dp0installer\Install-C7Bundle.ps1"
if not exist "%ENTRY%" (
  echo [FATAL] C7 installer entrypoint is missing:
  echo         %ENTRY%
  pause
  exit /b 2
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ENTRY%" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] M-LLM Workbench C7 installation failed. RC=%RC%
  echo Press any key to close.
  pause >nul
)
exit /b %RC%
