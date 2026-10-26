@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ========================================
echo   备课智能体 v2 · 启动器
echo ========================================

if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python -c "import fastapi, uvicorn, docx, pptx, openpyxl, pypdf, dotenv, openai" >nul 2>nul
  if errorlevel 1 goto :inst
  goto :run
)

echo 未发现虚拟环境，正在创建并安装依赖（首次约 2-5 分钟，请勿关闭本窗口）...
python -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" goto :inst
py -3 -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" goto :inst

echo.
echo [错误] 无法创建虚拟环境。请先安装 Python 3.10 或更高版本：
echo     https://www.python.org/downloads/
echo 安装时务必勾选 "Add python.exe to PATH"，然后重新双击本脚本。
echo.
pause
exit /b 1

:inst
echo 正在安装/补全依赖（使用清华镜像）...
.venv\Scripts\pip install -q --disable-pip-version-check -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo.
  echo [错误] 依赖安装失败。请检查网络，或手动执行：
  echo     .venv\Scripts\pip install -r requirements.txt
  echo 如果提示编码错误，请确认 requirements.txt 未被编辑器改成 GBK/带 BOM。
  echo.
  pause
  exit /b 1
)

:run
if not exist ".env" copy /y .env.example .env >nul
echo 启动服务：浏览器打开 http://127.0.0.1:8000  （关闭本窗口即停止）
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
