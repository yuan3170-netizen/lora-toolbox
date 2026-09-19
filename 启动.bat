@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PY_DIR=%~dp0python
set PY_EXE=%PY_DIR%\python.exe
set DEPS_FLAG=%PY_DIR%\.deps_ok

REM ============================================
REM  Step 1: Check VC++ Runtime
REM ============================================
echo.
echo [1/5] Checking VC++ Runtime...

set "VC_FILE=C:\Windows\System32\vcruntime140_1.dll"
set "VC_OK=0"

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Installed 2>nul | findstr /i "0x1" >nul
if %errorlevel% equ 0 (
    if exist "%VC_FILE%" set "VC_OK=1"
)

if "!VC_OK!"=="1" (
    echo       Installed.
    goto :vc_done
)

echo.
echo ================================================
echo  VC++ Runtime not found
echo  A UAC window will pop up - please click YES
echo ================================================
echo.

set "VC_INSTALLER=%TEMP%\vc_redist.x64.exe"
set "VC_URL=https://aka.ms/vs/17/release/vc_redist.x64.exe"

powershell -NoProfile -Command "Invoke-WebRequest -Uri '%VC_URL%' -OutFile '%VC_INSTALLER%'"
if errorlevel 1 goto :vc_fail

powershell -NoProfile -Command "Start-Process -FilePath '%VC_INSTALLER%' -ArgumentList '/install /quiet /norestart' -Verb RunAs -Wait"
del "%VC_INSTALLER%" 2>nul

set "VC_OK=0"
reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Installed 2>nul | findstr /i "0x1" >nul
if %errorlevel% equ 0 (
    if exist "%VC_FILE%" set "VC_OK=1"
)

if "!VC_OK!"=="1" (
    echo       Installed successfully.
    goto :vc_done
)

:vc_fail
echo.
echo ================================================
echo  Failed to install VC++ Runtime
echo ================================================
echo.
echo  Please install manually:
echo   1. Open browser: https://aka.ms/vs/17/release/vc_redist.x64.exe
echo   2. Download, run, click Next until done
echo   3. Restart the tool
echo.
pause
exit /b

:vc_done

REM ============================================
REM  Step 2: Check Python
REM ============================================
echo.
echo [2/5] Checking Python environment...

if exist "%PY_DIR%\Lib\tkinter" (
    echo       Installed.
    goto :py_done
)

if exist "%PY_DIR%" (
    echo       Found incomplete Python, cleaning up...
    rmdir /s /q "%PY_DIR%" 2>nul
)

echo       Python not found, downloading (about 28 MB)...
set "PY_INSTALLER=%TEMP%\python-3.10.11-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"

powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INSTALLER%'"
if errorlevel 1 (
    echo       Download failed. Please check your network.
    pause
    exit /b
)

echo       Installing (about 1 min, please wait)...
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 TargetDir="%PY_DIR%" Include_tcltk=1 Include_pip=1 Include_test=0 PrependPath=0 Shortcuts=0 AssociateFiles=0
del "%PY_INSTALLER%" 2>nul

if not exist "%PY_DIR%\Lib\tkinter" (
    echo.
    echo ================================================
    echo  Python installation failed
    echo ================================================
    echo.
    echo  Please install manually:
    echo   1. Open browser: https://www.python.org/downloads/release/python-31011/
    echo   2. Download Windows installer (64-bit)
    echo   3. Choose Customize installation, check tcl/tk and IDLE
    echo   4. Target path: %PY_DIR%
    echo   5. Restart the tool
    echo.
    pause
    exit /b
)
echo       Installed successfully.

:py_done

REM ============================================
REM  Step 3: Check Python dependencies
REM ============================================
echo.
echo [3/5] Checking Python dependencies...

if exist "%DEPS_FLAG%" (
    echo       Installed.
    goto :deps_done
)

echo.
echo ================================================
echo  First run: installing dependencies (3-10 min)
echo  First time will download PyTorch, please wait
echo ================================================
echo.

"%PY_EXE%" -m pip install --upgrade pip
"%PY_EXE%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed. Please check your network.
    pause
    exit /b
)
echo. > "%DEPS_FLAG%"
echo       Installed successfully.

:deps_done

REM ============================================
REM  Step 4: Check WD Tagger model
REM ============================================
echo.
echo [4/5] Checking WD Tagger model...

set "MODEL_DIR=%~dp0models\wd-eva02-large-tagger-v3"
set "MODEL_FILE=%MODEL_DIR%\model.onnx"
set "LABEL_FILE=%MODEL_DIR%\selected_tags.csv"
set "BASE_URL=https://hf-mirror.com/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main"

set "MODEL_OK=0"
set "LABEL_OK=0"

if exist "%MODEL_FILE%" (
    for %%A in ("%MODEL_FILE%") do (
        if %%~zA GTR 1000000000 set "MODEL_OK=1"
    )
)
if exist "%LABEL_FILE%" (
    for %%A in ("%LABEL_FILE%") do (
        if %%~zA GTR 100000 set "LABEL_OK=1"
    )
)

if "!MODEL_OK!"=="1" if "!LABEL_OK!"=="1" (
    echo       Installed.
    goto :model_done
)

echo.
echo ================================================
echo  WD Tagger model not found
echo  Required for WD tagging (about 1.2 GB)
echo  Download once, use forever
echo ================================================
echo.
choice /c YN /n /m "  Download now? [Y=Yes / N=Skip] "
if errorlevel 2 goto :model_skip

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%" 2>nul

echo.
echo      Downloading tags (about 250 KB)...
if exist "%LABEL_FILE%" del "%LABEL_FILE%" 2>nul
curl -L --fail --retry 3 --retry-delay 3 -o "%LABEL_FILE%" "%BASE_URL%/selected_tags.csv"
if errorlevel 1 goto :model_fail

for %%A in ("%LABEL_FILE%") do set "LABEL_SIZE=%%~zA"
if !LABEL_SIZE! LSS 100000 (
    echo      Tag file size abnormal, download failed
    del "%LABEL_FILE%" 2>nul
    goto :model_fail
)
echo      Tags downloaded.

echo.
echo      Downloading model (about 1.2 GB, 5-30 min, please wait)...
echo      If interrupted, just run again - it will resume
echo.
if exist "%MODEL_FILE%" del "%MODEL_FILE%" 2>nul
curl -L --fail --retry 3 --retry-delay 3 -o "%MODEL_FILE%" "%BASE_URL%/model.onnx"
if errorlevel 1 goto :model_fail

for %%A in ("%MODEL_FILE%") do set "MODEL_SIZE=%%~zA"
if !MODEL_SIZE! LSS 1000000000 (
    echo      Model size abnormal, download failed
    del "%MODEL_FILE%" 2>nul
    goto :model_fail
)
echo      Model downloaded.
goto :model_done

:model_skip
echo      Skipped. To use WD tagging later, download these two files:
echo      %MODEL_DIR%
echo        - model.onnx
echo        - selected_tags.csv
goto :model_done

:model_fail
echo.
echo ================================================
echo  Model download failed
echo ================================================
echo.
echo  Please download manually:
echo   1. Open browser: https://hf-mirror.com/SmilingWolf/wd-eva02-large-tagger-v3/tree/main
echo   2. Download these two files:
echo        model.onnx         (about 1.17 GB)
echo        selected_tags.csv  (about 250 KB)
echo   3. Put into: %MODEL_DIR%
echo.
echo  (The tool will continue. WD tagging unavailable for now.)
echo.
pause

:model_done

REM ============================================
REM  Step 5: Launch
REM ============================================
echo.
echo [5/5] Launching tool...
cd /d "%~dp0scripts"
start "" "%PY_DIR%\pythonw.exe" lora_tool.py
exit