@echo off
setlocal EnableExtensions

set "MLLM_ORIGINAL_ARGS=%*"
set "MLLM_FORCE_LEGACY=0"
call :detect_legacy %*

if /I "%~1"=="--legacy" (
  set "MLLM_FORCE_LEGACY=1"
  shift
)

set "MLLM_DESKTOP_EXE=%~dp0desktop\MLLM.Workbench.Desktop.exe"
if "%MLLM_FORCE_LEGACY%"=="0" if exist "%MLLM_DESKTOP_EXE%" (
  if "%MLLM_LAUNCHER_TEST%"=="1" (
    echo MLLM_LAUNCH_TARGET=DESKTOP
    exit /b 0
  )
  "%MLLM_DESKTOP_EXE%" %*
  exit /b %ERRORLEVEL%
)

if "%MLLM_LAUNCHER_TEST%"=="1" (
  echo MLLM_LAUNCH_TARGET=LEGACY
  exit /b 0
)

set "PSARGS="
:parse
if "%~1"=="" goto run
if /I "%~1"=="--legacy" shift& goto parse
if /I "%~1"=="--cli" set "PSARGS=%PSARGS% -Cli"& shift& goto parse
if /I "%~1"=="--doctor" set "PSARGS=%PSARGS% -Doctor"& shift& goto parse
if /I "%~1"=="--gui" set "PSARGS=%PSARGS% -Gui"& shift& goto parse
if /I "%~1"=="--start-service" set "PSARGS=%PSARGS% -StartService"& shift& goto parse
if /I "%~1"=="--stop-service" set "PSARGS=%PSARGS% -StopService"& shift& goto parse
if /I "%~1"=="--start-web" set "PSARGS=%PSARGS% -StartWeb"& shift& goto parse
if /I "%~1"=="--stop-web" set "PSARGS=%PSARGS% -StopWeb"& shift& goto parse
if /I "%~1"=="--preset" set "PSARGS=%PSARGS% -Preset "%~2""& shift& shift& goto parse
if /I "%~1"=="--network-mode" set "PSARGS=%PSARGS% -NetworkMode "%~2""& shift& shift& goto parse
set "PSARGS=%PSARGS% %1"
shift
goto parse

:run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start_M_LLM_Workbench.ps1" %PSARGS%
set "MLLM_RC=%ERRORLEVEL%"
if not "%MLLM_RC%"=="0" if "%MLLM_ORIGINAL_ARGS%"=="" (
  echo.
  echo M-LLM did not exit normally. Diagnostic information is shown above.
  echo Press any key after recording the EVIDENCE path.
  pause >nul
)
exit /b %MLLM_RC%

:detect_legacy
if "%~1"=="" exit /b 0
if /I "%~1"=="--legacy" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--cli" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--doctor" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--start-service" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--stop-service" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--start-web" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--stop-web" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--preset" set "MLLM_FORCE_LEGACY=1"& exit /b 0
if /I "%~1"=="--network-mode" set "MLLM_FORCE_LEGACY=1"& exit /b 0
shift
goto detect_legacy
