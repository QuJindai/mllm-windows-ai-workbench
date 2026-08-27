@echo off
setlocal EnableExtensions EnableDelayedExpansion
title M-LLM Windows AI Workbench - Full Test R4

rem ============================================================
rem M-LLM Windows AI Workbench - FULL TEST R4
rem Locale-safe Windows PowerShell 5.1 entrypoint validation.
rem Default:
rem   download/reuse -> locale/encoding gate -> bootstrap
rem   -> physical preflight -> GUI dashboard preflight -> GUI
rem Safety:
rem   OFFLINE_CACHE + isolated runtime data; no Core install authorization.
rem ============================================================

set "COMMIT=b576c87b541ad95474e2ce89a4dc12af29e66325"
set "MODE=gui"
set "REFRESH=0"
set "NOPAUSE=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--gui" set "MODE=gui"& shift& goto parse_args
if /I "%~1"=="--doctor" set "MODE=doctor"& shift& goto parse_args
if /I "%~1"=="--cli" set "MODE=cli"& shift& goto parse_args
if /I "%~1"=="--preflight-only" set "MODE=preflight"& shift& goto parse_args
if /I "%~1"=="--gui-preflight-only" set "MODE=gui-preflight"& shift& goto parse_args
if /I "%~1"=="--refresh" set "REFRESH=1"& shift& goto parse_args
if /I "%~1"=="--no-pause" set "NOPAUSE=1"& shift& goto parse_args
if /I "%~1"=="--help" goto help
if /I "%~1"=="-h" goto help
if /I "%~1"=="/?" goto help
echo [ERROR] Unknown option: %~1
goto help_error

:args_done
echo.
echo ============================================================
echo  M-LLM Windows AI Workbench - FULL TEST R4
echo ============================================================
echo  Commit : %COMMIT%
echo  Mode   : %MODE%
echo  Policy : LOCALE-SAFE + NON-INSTALLING + OFFLINE_CACHE
echo ============================================================
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [FATAL] Windows PowerShell was not found.
  goto fatal
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$v=$PSVersionTable.PSVersion; Write-Host ('[INFO] PowerShell ' + $v); Write-Host ('[INFO] Culture=' + [Globalization.CultureInfo]::CurrentCulture.Name + ' ANSI=' + [Text.Encoding]::Default.CodePage); if($v.Major -lt 5){exit 5}"
if errorlevel 1 (
  echo [FATAL] PowerShell 5.1 or later is required.
  goto fatal
)

set "BASE=%USERPROFILE%\Downloads"
if not exist "%BASE%" set "BASE=%TEMP%"
set "ROOT=%BASE%\M_LLM_WORKBENCH_FULL_TEST_R4"
set "SRC=%ROOT%\source"
set "UNPACK=%ROOT%\unpack"
set "ZIP=%ROOT%\source_%COMMIT%.zip"
set "STAMP=%SRC%\.mllm_verified_commit"
set "EVIDENCE=%ROOT%\evidence"
set "RUNTIME=%ROOT%\runtime-test"
set "URL=https://github.com/QuJindai/mllm-windows-ai-workbench/archive/%COMMIT%.zip"

if not exist "%ROOT%" mkdir "%ROOT%" >nul 2>&1
if not exist "%ROOT%" (
  echo [FATAL] Cannot create work root: %ROOT%
  goto fatal
)

echo [INFO] Work root: %ROOT%

if "%REFRESH%"=="1" (
  echo [INFO] Refresh requested. Removing cached source.
  if exist "%SRC%" rmdir /s /q "%SRC%" >nul 2>&1
  if exist "%UNPACK%" rmdir /s /q "%UNPACK%" >nul 2>&1
  if exist "%ZIP%" del /f /q "%ZIP%" >nul 2>&1
)

set "CACHE_OK=0"
if exist "%SRC%\Start_M_LLM_Workbench.ps1" if exist "%SRC%\Bootstrap_SafeCore.ps1" if exist "%SRC%\M_LLM_GUI_PREFLIGHT.ps1" if exist "%STAMP%" (
  set /p "CACHED_COMMIT="<"%STAMP%"
  if /I "!CACHED_COMMIT!"=="%COMMIT%" set "CACHE_OK=1"
)

if "%CACHE_OK%"=="1" (
  echo [PASS] Reusing exact verified source snapshot.
  goto source_ready
)

echo [INFO] Downloading exact verified source snapshot...
set "MLLM_URL=%URL%"
set "MLLM_ZIP=%ZIP%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri $env:MLLM_URL -OutFile $env:MLLM_ZIP; $f=Get-Item -LiteralPath $env:MLLM_ZIP; if($f.Length -lt 1024){throw 'Downloaded ZIP is unexpectedly small'}; Write-Host ('[PASS] Downloaded ' + $f.Length + ' bytes')"
if errorlevel 1 (
  echo [FATAL] Source download failed.
  goto fatal
)

if exist "%UNPACK%" rmdir /s /q "%UNPACK%" >nul 2>&1
mkdir "%UNPACK%" >nul 2>&1
set "MLLM_UNPACK=%UNPACK%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath $env:MLLM_ZIP -DestinationPath $env:MLLM_UNPACK -Force"
if errorlevel 1 (
  echo [FATAL] Source extraction failed.
  goto fatal
)

set "EXTRACTED="
for /d %%D in ("%UNPACK%\*") do (
  if exist "%%~fD\Start_M_LLM_Workbench.ps1" set "EXTRACTED=%%~fD"
)
if not defined EXTRACTED (
  echo [FATAL] Extracted repository root was not found.
  goto fatal
)
if not exist "!EXTRACTED!\Bootstrap_SafeCore.ps1" (
  echo [FATAL] Bootstrap_SafeCore.ps1 missing from snapshot.
  goto fatal
)
if not exist "!EXTRACTED!\M_LLM_PHYSICAL_PREFLIGHT.ps1" (
  echo [FATAL] M_LLM_PHYSICAL_PREFLIGHT.ps1 missing from snapshot.
  goto fatal
)
if not exist "!EXTRACTED!\M_LLM_GUI_PREFLIGHT.ps1" (
  echo [FATAL] M_LLM_GUI_PREFLIGHT.ps1 missing from snapshot.
  goto fatal
)

if exist "%SRC%" rmdir /s /q "%SRC%" >nul 2>&1
move "!EXTRACTED!" "%SRC%" >nul
if errorlevel 1 (
  echo [FATAL] Cannot activate source snapshot.
  goto fatal
)
>"%STAMP%" echo %COMMIT%
if exist "%UNPACK%" rmdir /s /q "%UNPACK%" >nul 2>&1

:source_ready
for %%F in (Start_M_LLM_Workbench.ps1 Bootstrap_SafeCore.ps1 M_LLM_PHYSICAL_PREFLIGHT.ps1 M_LLM_GUI_PREFLIGHT.ps1) do (
  if not exist "%SRC%\%%F" (
    echo [FATAL] Required source file missing: %%F
    goto fatal
  )
)
echo [PASS] Source entrypoints validated.

echo.
echo [1/5] Windows PowerShell 5.1 locale/encoding gate...
set "MLLM_SRC=%SRC%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $names=@('Bootstrap_SafeCore.ps1','M_LLM_PHYSICAL_PREFLIGHT.ps1','M_LLM_GUI_PREFLIGHT.ps1','Start_M_LLM_Workbench.ps1'); foreach($n in $names){$p=Join-Path $env:MLLM_SRC $n; [byte[]]$b=[IO.File]::ReadAllBytes($p); if($null -ne ($b | Where-Object {$_ -gt 127} | Select-Object -First 1)){throw ('Non-ASCII byte in direct PS5.1 entrypoint: ' + $n)}; $tokens=$null; $errs=$null; [void][Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errs); if(@($errs).Count -gt 0){throw ('PS5.1 parse failed for ' + $n + ': ' + (($errs | ForEach-Object {$_.Message}) -join ' | '))}; Write-Host ('[PASS] locale-safe parse: ' + $n)}"
if errorlevel 1 (
  echo [BLOCKED] Locale/encoding compatibility gate failed.
  echo [INFO] No Core installation was authorized.
  goto blocked
)
echo [PASS] Locale/encoding compatibility gate completed.

echo.
echo [2/5] Safe Core bootstrap...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SRC%\Bootstrap_SafeCore.ps1" -ProjectRoot "%SRC%"
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
  echo [FATAL] Bootstrap failed. RC=!RC!
  goto fatal
)
if not exist "%SRC%\engine\Core.psm1" (
  echo [FATAL] Bootstrap returned success but engine\Core.psm1 is missing.
  goto fatal
)
echo [PASS] Safe Core bootstrap completed.

echo.
echo [3/5] NON-INSTALLING physical preflight...
if not exist "%EVIDENCE%" mkdir "%EVIDENCE%" >nul 2>&1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SRC%\M_LLM_PHYSICAL_PREFLIGHT.ps1" -DataRoot "%EVIDENCE%"
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
  echo [BLOCKED] Physical preflight did not pass. RC=!RC!
  echo [INFO] Evidence root: %EVIDENCE%
  goto blocked
)
echo [PASS] Physical preflight completed.
echo [INFO] Evidence root: %EVIDENCE%

if /I "%MODE%"=="preflight" goto success

if exist "%RUNTIME%" rmdir /s /q "%RUNTIME%" >nul 2>&1
mkdir "%RUNTIME%" >nul 2>&1
if not exist "%RUNTIME%" (
  echo [FATAL] Cannot create isolated runtime data root.
  goto fatal
)

echo.
echo [4/5] NON-INSTALLING GUI dashboard preflight...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SRC%\M_LLM_GUI_PREFLIGHT.ps1" -DataRoot "%RUNTIME%" -NetworkMode OFFLINE_CACHE
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
  echo [BLOCKED] GUI dashboard preflight did not pass. RC=!RC!
  echo [INFO] GUI report: %RUNTIME%\gui_preflight.json
  goto blocked
)
if not exist "%RUNTIME%\gui_preflight.json" (
  echo [FATAL] GUI preflight returned success but report is missing.
  goto fatal
)
echo [PASS] GUI dashboard preflight completed with snapshot_errors=0.

if /I "%MODE%"=="gui-preflight" goto success

echo.
echo [5/5] Starting %MODE% in isolated OFFLINE_CACHE mode...
echo [INFO] Runtime data: %RUNTIME%

if /I "%MODE%"=="gui" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SRC%\Start_M_LLM_Workbench.ps1" -Gui -DataRoot "%RUNTIME%" -NetworkMode OFFLINE_CACHE
  set "RC=!ERRORLEVEL!"
  goto app_done
)
if /I "%MODE%"=="doctor" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SRC%\Start_M_LLM_Workbench.ps1" -Doctor -DataRoot "%RUNTIME%" -NetworkMode OFFLINE_CACHE
  set "RC=!ERRORLEVEL!"
  goto app_done
)
if /I "%MODE%"=="cli" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SRC%\Start_M_LLM_Workbench.ps1" -Cli -DataRoot "%RUNTIME%" -NetworkMode OFFLINE_CACHE
  set "RC=!ERRORLEVEL!"
  goto app_done
)

echo [FATAL] Internal mode dispatch error: %MODE%
goto fatal

:app_done
if "!RC!"=="0" goto success
if /I "%MODE%"=="doctor" if "!RC!"=="1" (
  echo [INFO] Doctor returned RC=1 because health findings need attention.
  goto success
)
echo [ERROR] M-LLM %MODE% exited with RC=!RC!
goto blocked

:success
echo.
echo ============================================================
echo  TEST COMPLETE
echo  Locale encoding gate    : PASS
echo  Core install authorized : NO
echo  Network install path     : OFFLINE_CACHE
echo  Physical evidence        : %EVIDENCE%
echo  GUI preflight report     : %RUNTIME%\gui_preflight.json
echo  Source                   : %SRC%
echo ============================================================
echo.
if "%NOPAUSE%"=="0" (
  echo Press any key to close.
  pause >nul
)
exit /b 0

:blocked
echo.
echo ============================================================
echo  TEST STOPPED SAFELY
echo  Core installation was not authorized by this launcher.
echo  Physical evidence: %EVIDENCE%
echo  GUI report: %RUNTIME%\gui_preflight.json
echo ============================================================
echo.
if "%NOPAUSE%"=="0" (
  echo Press any key to close.
  pause >nul
)
exit /b 1

:fatal
echo.
echo ============================================================
echo  FATAL TEST ERROR
echo  Core installation was not authorized by this launcher.
echo  Work root: %ROOT%
echo ============================================================
echo.
if "%NOPAUSE%"=="0" (
  echo Press any key to close.
  pause >nul
)
exit /b 2

:help
echo.
echo M_LLM_WORKBENCH_FULL_TEST_R4.cmd
echo.
echo Double-click:
echo   exact source - locale gate - bootstrap - physical preflight - GUI preflight - GUI.
echo.
echo Options:
echo   --gui                 Full safe test then GUI ^(default^)
echo   --doctor              All preflights then Doctor
echo   --cli                 All preflights then CLI
echo   --preflight-only      Locale gate + bootstrap + physical preflight
echo   --gui-preflight-only  Locale gate + physical + real GUI Dashboard preflight, no GUI window
echo   --refresh             Re-download pinned source
echo   --no-pause            Do not wait at exit ^(CI use^)
echo   --help                Show help
echo.
exit /b 0

:help_error
echo Use --help for supported options.
if "%NOPAUSE%"=="0" pause
exit /b 64
