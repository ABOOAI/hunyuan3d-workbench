@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0hunyuan_workbench.py" %*
) else (
    python "%~dp0hunyuan_workbench.py" %*
)
exit /b %errorlevel%
