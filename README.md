# Tim20 Air Quality

## Prerequisites

Make sure you have installed:

- [Node.js](https://nodejs.org/)
- [Python](https://www.python.org/) + virtual environment set up in `backend/python-ai/venv`

## Starting the Backend

From the project root (`Tim20-Air-Quality/`), run:

```powershell
.\start-dev.bat
```

This will open two terminal windows:

- **Python AI** running on `http://localhost:5000`
- **Node.js API** running on `http://localhost:3000`

## API Endpoints

| Method | URL                | Description         |
| ------ | ------------------ | ------------------- |
| GET    | `/api/air`         | Current air quality |
| GET    | `/api/predictions` | 24h AQI prediction  |
| GET    | `/api/users`       | Users               |

## First Time Setup

### Node.js

```powershell
cd backend/node-backend
npm install
```

### Python

```powershell
cd backend/python-ai
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
