@echo off
rem 摸鱼阅读器启动脚本 - pythonw 无控制台黑窗
cd /d %~dp0
start "" ".venv\Scripts\pythonw.exe" main.py
