@echo off
rem StorCLI GUI 启动器: 优先使用 pythonw (无黑窗)
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0storcli_gui.py"
    goto :eof
)
where py >nul 2>nul
if %errorlevel%==0 (
    start "" py -3 "%~dp0storcli_gui.py"
    goto :eof
)
start "" python "%~dp0storcli_gui.py"
