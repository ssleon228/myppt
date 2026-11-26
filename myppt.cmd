@echo off
chcp 65001 >nul
setlocal
rem 用法：myppt.cmd 命令 参数…（命令见 run.py；把 deck.json 拖到本文件上 = 在同目录生成同名 .pptx）
set "HERE=%~dp0"
set "PY="
if exist "%HERE%runtime\python.exe" set "PY="%HERE%runtime\python.exe""
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo 找不到 Python：请使用带 runtime 文件夹的完整包，或安装 Python 3.8 以上。
  pause
  exit /b 1
)
if "%~1"=="" (
  %PY% "%HERE%run.py" help
  pause
  exit /b 0
)
if /i "%~x1"==".json" if "%~2"=="" (
  %PY% "%HERE%run.py" make "%~1" "%~dpn1.pptx"
  pause
  exit /b %errorlevel%
)
%PY% "%HERE%run.py" %*
