@echo off
cd /d "%~dp0"
if exist data\app.db del /q data\app.db
if exist data\risk_model.joblib del /q data\risk_model.joblib
echo Demo data reset. Start the backend again to reseed synthetic cases.
pause
