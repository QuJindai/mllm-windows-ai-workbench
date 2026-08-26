@echo off
setlocal EnableExtensions
set "MLLM_ORIGINAL_ARGS=%*"
set "PSARGS="
:parse
if "%~1"=="" goto run
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
