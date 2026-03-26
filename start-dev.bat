@echo off
set ROOT=%~dp0

echo Starting Python AI backend...
start cmd /k "cd /d %ROOT%backend\python-ai && venv\Scripts\activate && python app.py"

echo Starting Node.js backend...
start cmd /k "cd /d %ROOT%backend\node-backend && npm run dev"

echo Both servers are starting...