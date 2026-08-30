@echo off
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
python -m backend.train_model
python -m uvicorn backend.main:app --reload
