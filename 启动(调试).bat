@echo off
chcp 65001 >nul
cd /d "%~dp0scripts"
"..\python\python.exe" lora_tool.py
pause