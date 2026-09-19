@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PY_DIR=%~dp0python
set PY_EXE=%PY_DIR%\python.exe
set DEPS_FLAG=%PY_DIR%\.deps_ok

REM ============================================
REM  第 1 步：检查 VC++ 运行库
REM ============================================
echo.
echo [1/5] 检查 VC++ 运行库...

set "VC_FILE=C:\Windows\System32\vcruntime140_1.dll"
set "VC_OK=0"

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" /v Installed 2>nul | findstr /i "0x1" >nul
if %errorlevel% equ 0 (
    if exist "%VC_FILE%" set "VC_OK=1"
)

if "!VC_OK!"=="1" (
    echo      已安装
    goto :vc_done
)

echo.
echo ================================================
echo  检测到缺少 VC++ 运行库，即将自动安装
echo  屏幕上会弹出一个 UAC 窗口，请点击"是"
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
    echo      安装成功
    goto :vc_done
)

:vc_fail
echo.
echo ================================================
echo  自动安装 VC++ 运行库失败
echo ================================================
echo.
echo  请手动安装：
echo   1. 浏览器访问
echo      https://aka.ms/vs/17/release/vc_redist.x64.exe
echo   2. 下载后双击运行，一直点“下一步”
echo   3. 装完重新双击 启动.bat
echo.
pause
exit /b

:vc_done

REM ============================================
REM  第 2 步：检查 Python（含 tkinter）
REM ============================================
echo.
echo [2/5] 检查 Python 环境...

if exist "%PY_DIR%\Lib\tkinter" (
    echo      已安装
    goto :py_done
)

if exist "%PY_DIR%" (
    echo      检测到不完整的 Python，正在清理...
    rmdir /s /q "%PY_DIR%" 2>nul
)

echo      Python 未安装，正在自动下载（约 28 MB）...
set "PY_INSTALLER=%TEMP%\python-3.10.11-amd64.exe"
set "PY_URL=https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"

powershell -NoProfile -Command "Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_INSTALLER%'"
if errorlevel 1 (
    echo      下载失败，请检查网络。
    pause
    exit /b
)

echo      正在安装（约 1 分钟，请稍候）...
start /wait "" "%PY_INSTALLER%" /quiet InstallAllUsers=0 TargetDir="%PY_DIR%" Include_tcltk=1 Include_pip=1 Include_test=0 PrependPath=0 Shortcuts=0 AssociateFiles=0
del "%PY_INSTALLER%" 2>nul

if not exist "%PY_DIR%\Lib\tkinter" (
    echo.
    echo ================================================
    echo  Python 安装失败
    echo ================================================
    echo.
    echo  请手动安装：
    echo   1. 浏览器访问
    echo      https://www.python.org/downloads/release/python-31011/
    echo   2. 下载 Windows installer (64-bit)
    echo   3. 安装时选 Customize installation
    echo      勾选 tcl/tk and IDLE
    echo      路径填：%PY_DIR%
    echo   4. 装完重新双击 启动.bat
    echo.
    pause
    exit /b
)
echo      安装成功

:py_done

REM ============================================
REM  第 3 步：检查 Python 依赖包
REM ============================================
echo.
echo [3/5] 检查 Python 依赖包...

if exist "%DEPS_FLAG%" (
    echo      已安装
    goto :deps_done
)

echo.
echo ================================================
echo  首次运行，正在安装依赖（约 3-10 分钟）
echo  第一次会下载 PyTorch，比较大，请耐心等待
echo ================================================
echo.

"%PY_EXE%" -m pip install --upgrade pip
"%PY_EXE%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b
)
echo. > "%DEPS_FLAG%"
echo      依赖安装完成

:deps_done

REM ============================================
REM  第 4 步：检查 WD 打标模型
REM ============================================
echo.
echo [4/5] 检查 WD 打标模型...

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
    echo      已安装
    goto :model_done
)

echo.
echo ================================================
echo  未检测到完整的 WD 打标模型
echo  这是「WD 打标」功能需要的模型（约 1.2 GB）
echo  只需下载一次，以后不用再下
echo ================================================
echo.
choice /c YN /n /m "  现在下载吗？[Y=下载 / N=跳过] "
if errorlevel 2 goto :model_skip

if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%" 2>nul

echo.
echo      正在下载标签表（约 250 KB）...
if exist "%LABEL_FILE%" del "%LABEL_FILE%" 2>nul
curl -L --fail --retry 3 --retry-delay 3 -o "%LABEL_FILE%" "%BASE_URL%/selected_tags.csv"
if errorlevel 1 goto :model_fail

for %%A in ("%LABEL_FILE%") do set "LABEL_SIZE=%%~zA"
if !LABEL_SIZE! LSS 100000 (
    echo      标签表大小异常，下载失败
    del "%LABEL_FILE%" 2>nul
    goto :model_fail
)
echo      标签表下载完成

echo.
echo      正在下载模型（约 1.2 GB，5-30 分钟，请耐心等待）...
echo      如下载中断，可重新运行脚本再次下载
echo.
if exist "%MODEL_FILE%" del "%MODEL_FILE%" 2>nul
curl -L --fail --retry 3 --retry-delay 3 -o "%MODEL_FILE%" "%BASE_URL%/model.onnx"
if errorlevel 1 goto :model_fail

for %%A in ("%MODEL_FILE%") do set "MODEL_SIZE=%%~zA"
if !MODEL_SIZE! LSS 1000000000 (
    echo      模型大小异常，下载失败
    del "%MODEL_FILE%" 2>nul
    goto :model_fail
)
echo      模型下载完成
goto :model_done

:model_skip
echo      已跳过。以后想用 WD 打标，手动把这两个文件放到：
echo      %MODEL_DIR%
echo        - model.onnx
echo        - selected_tags.csv
goto :model_done

:model_fail
echo.
echo ================================================
echo  模型自动下载失败
echo ================================================
echo.
echo  请手动下载（推荐用浏览器或下载工具）：
echo   1. 浏览器访问
echo      https://hf-mirror.com/SmilingWolf/wd-eva02-large-tagger-v3/tree/main
echo   2. 下载这两个文件：
echo        model.onnx         （约 1.17 GB）
echo        selected_tags.csv  （约 250 KB）
echo   3. 放到这个文件夹：
echo      %MODEL_DIR%
echo.
echo  （程序会继续启动，WD 打标功能暂时不可用）
echo.
pause

:model_done

REM ============================================
REM  第 5 步：启动程序（无黑窗）
REM ============================================
echo.
echo [5/5] 启动程序...
cd /d "%~dp0scripts"
start "" "%PY_DIR%\pythonw.exe" lora_tool.py
exit