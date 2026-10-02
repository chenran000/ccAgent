@echo off
rem TestAssistant AI 一键构建脚本(Windows): 前端 + 后端 onedir + 桌面壳
rem 前置: Python 3.12(venv 已建)、Node 20
cd /d "%~dp0"

echo [1/4] 构建前端...
cd frontend-react
call npm install --no-audit --no-fund
call npm run build
cd ..

echo [2/4] PyInstaller 打包后端(onedir)...
venv\Scripts\pyinstaller.exe --noconfirm --clean testassistant.spec
if errorlevel 1 goto :fail

echo [3/4] PyInstaller 打包桌面壳(onefile)...
venv\Scripts\pyinstaller.exe --noconfirm --clean testassistant_app.spec
if errorlevel 1 goto :fail

echo [4/4] 组装 dist\testassistant\...
xcopy /E /I /Y frontend dist\testassistant\frontend >nul
copy /Y dist\TestAssistantApp.exe dist\testassistant\ >nul
del dist\TestAssistantApp.exe

echo.
echo 完成: dist\testassistant\TestAssistantApp.exe (双击启动,独立窗口)
echo 数据目录: %%USERPROFILE%%\.testassistant (可用 TESTASSISTANT_STORAGE_DIR 重定向)
pause
exit /b 0

:fail
echo 构建失败,请查看上方日志
pause
