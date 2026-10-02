@echo off
rem TestAssistant AI 一键构建脚本(Windows)
rem 前置: Python 3.12(venv)、Node 20
cd /d "%~dp0"

echo [1/3] 构建前端...
cd frontend-react
call npm install --no-audit --no-fund
call npm run build
cd ..

echo [2/3] PyInstaller 打包...
venv\Scripts\pyinstaller.exe --noconfirm --clean testassistant.spec

echo [3/3] 拷贝前端产物到 exe 旁边...
xcopy /E /I /Y frontend dist\testassistant\frontend >nul

echo 完成: dist\testassistant\TestAssistant.exe
echo 数据目录: %%USERPROFILE%%\.testassistant (可用 TESTASSISTANT_STORAGE_DIR 重定向)
pause
