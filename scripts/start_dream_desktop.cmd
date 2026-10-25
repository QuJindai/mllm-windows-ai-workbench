@echo off
setlocal
chcp 65001 >nul
title Dream Browser Workstation
set "DREAM_STARTER=E:\Dream\repo\scripts\start_dream_web_background.ps1"
set "DREAM_PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"

if not exist "%DREAM_PWSH%" (
  echo PowerShell 7 was not found: %DREAM_PWSH%
  pause
  exit /b 1
)
if not exist "%DREAM_STARTER%" (
  echo Dream launcher was not found: %DREAM_STARTER%
  pause
  exit /b 1
)

"%DREAM_PWSH%" -NoLogo -NoProfile -File "%DREAM_STARTER%" -Port 8766
if errorlevel 1 (
  echo.
  echo Dream failed to start. See E:\Dream\logs for details.
  pause
  exit /b 1
)
exit /b 0
