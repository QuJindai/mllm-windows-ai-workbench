@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_stable_diffusion_wrapper.ps1" %*
exit /b %ERRORLEVEL%
