@echo off
rem PC でローカル表示するとき用。ブラウザで http://localhost:8787 が開きます。
cd /d "%~dp0"
start "" http://localhost:8787/
python -m http.server 8787
