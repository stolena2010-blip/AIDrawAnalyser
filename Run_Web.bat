@echo off
REM AIDrawAnalyser - Streamlit server on port 8502
cd /d "%~dp0"
call .venv\Scripts\activate.bat
streamlit run app.py --server.port 8502
pause
