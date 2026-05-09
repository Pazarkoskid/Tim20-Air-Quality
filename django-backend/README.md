<div align="center">

# 🌬️ Air Quality AI – Скопје

**Интелигентен систем за следење, анализа и предвидување на квалитетот на воздухот во Скопје**

[![Python](https://img.shields.io/badge/Python-3.13+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5.x-092e20?style=flat-square&logo=django&logoColor=white)](https://djangoproject.com)
[![TensorFlow](https://img.shields.io/badge/TensorFlow%20%2F%20Keras-BiLSTM-ff6f00?style=flat-square&logo=tensorflow&logoColor=white)](https://tensorflow.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-336791?style=flat-square&logo=postgresql&logoColor=white)](https://supabase.com)

**Тим 20 · Управување со ИКТ проекти · 2025/2026**

</div>

---

## 📋 Опис

**Air Quality AI – Скопје** е веб апликација која во реално време ги следи нивоата на загаденост на воздухот во Скопје, визуелизира историски трендови и генерира AI прогнози за следните 72 часа преку BiLSTM невронска мрежа.

---

## 🗂️ Структура на проектот

```
Tim20-Air-Quality/
├── django-backend/
│   ├── airquality/
│   │   ├── management/
│   │   │   └── commands/
│   │   │       ├── add_test_data.py       # Генерира 360 тест записи
│   │   │       └── runscheduler.py        # APScheduler за автоматско прибирање
│   │   ├── migrations/
│   │   │   ├── 0001_initial.py
│   │   │   ├── 0002_userprofile_phone_savedlocation.py
│   │   │   └── 0003_userprofile_avatar.py
│   │   ├── static/
│   │   │   ├── avatars/
│   │   │   │   ├── avatar1.svg            # Профилни слики
│   │   │   │   ├── avatar2.svg
│   │   │   │   └── avatar3.svg
│   │   │   ├── fonts/
│   │   │   │   ├── DejaVuSans.ttf         # Кирилица во PDF
│   │   │   │   └── DejaVuSans-Bold.ttf
│   │   │   └── sw.js                      # Service Worker за push известувања
│   │   ├── templates/airquality/
│   │   │   ├── base.html                  # Главен layout (sidebar, topbar, theme)
│   │   │   ├── login.html                 # Најава
│   │   │   ├── register.html              # Регистрација
│   │   │   ├── dashboard.html             # Контролна табла
│   │   │   ├── map.html                   # Leaflet интерактивна мапа
│   │   │   ├── history.html               # Историски податоци + пагинација
│   │   │   ├── forecast.html              # AI прогноза 24/48/72h
│   │   │   ├── notifications.html         # Известувања (7 по страница)
│   │   │   ├── settings.html              # Кориснички профил + аватар
│   │   │   └── about.html                 # AQI скала + упатство
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── forms.py
│   │   ├── models.py                      # AirQualityRecord, Forecast, Notification, UserProfile, SavedLocation
│   │   ├── services.py                    # Fetch, BiLSTM AI forecast, notifications, trends
│   │   ├── signals.py
│   │   └── urls.py
│   ├── core/
│   │   ├── settings.py                    # Django конфигурација + PostgreSQL
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── manage.py
│   └── requirements.txt
├── backend/
│   ├── python-ai/
│   │   ├── artifacts/
│   │   │   ├── 24h/                       # BiLSTM модел за 24h прогноза
│   │   │   │   ├── model.keras
│   │   │   │   ├── scaler.pkl
│   │   │   │   ├── meta.json
│   │   │   │   └── selected_features.json
│   │   │   ├── 48h/                       # BiLSTM модел за 48h прогноза
│   │   │   └── 72h/                       # BiLSTM модел за 72h прогноза
│   │   ├── app.py                         # FastAPI сервис
│   │   ├── ml_service.py
│   │   └── routes.py
│   └── node-backend/
│       └── src/
│           ├── app.js
│           ├── controllers/
│           ├── routes/
│           └── services/
└── README.md
```

---

## ✨ Функционалности

| Модул | Опис |
|-------|------|
| 📊 **Контролна табла** | Тековен AQI, загадувачи PM2.5/PM10/NO₂/CO, 24h граф, прогноза 72h |
| 🗺️ **Интерактивна мапа** | Leaflet мапа со 9 мерни станици по општини, popup со вредности |
| 📈 **Историја** | Филтри 24h/7d/30d/custom, JS пагинација, рангирање, споредба |
| 🤖 **AI Прогноза** | BiLSTM модел, предвидувања 24h/48h/72h, копче за регенерирање |
| 🔔 **Известувања** | 7 по страница, push + email при надминување на праг |
| ⚙️ **Поставки** | Профил, аватар (3 избори), локации, прагови, промена лозинка |
| 📤 **Извоз** | CSV (UTF-8 BOM), PDF (кирилица преку DejaVu фонт) |
| ℹ️ **About** | AQI скала со бои, упатство, опис на загадувачи |

---

## 🚀 Инсталација и покренување

### Барања

- Python 3.13+
- Git

### 1. Клонирање

```bash
git clone https://github.com/Pazarkoskid/Tim20-Air-Quality.git
cd Tim20-Air-Quality/django-backend
```



### 2. Инсталирај зависности

Прво инсталирај ги зависностите од главниот директориум:

```bash
# Во Tim20-Air-Quality/ (главниот директориум)
pip install -r requirements.txt
```

Потоа влези во `django-backend` и продолжи оттука:

```bash
cd django-backend
```

### 3. Виртуелна средина

```bash
# Создај
python -m venv venv

# Активирај (Windows)
venv\Scripts\activate

# Активирај (macOS/Linux)
source venv/bin/activate
```

```bash
pip install -r requirements.txt
```

### 4. Конфигурација (`.env`)

Создај `django-backend/.env`:

```env
SECRET_KEY=твојот-secret-key
DEBUG=True
OPENWEATHER_API_KEY=твојот-api-key
CITY_LAT=41.9981
CITY_LON=21.4254
CITY_NAME=Скопје

# PostgreSQL / Supabase
DB_NAME=postgres
DB_USER=postgres.ТВОЈОТ_PROJECT_ID
DB_PASSWORD=твојата_лозинка
DB_HOST=aws-0-eu-central-1.pooler.supabase.com
DB_PORT=5432
```

> 💡 Генерирај `SECRET_KEY`:
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(50))"
> ```

### 5. Миграции

```bash
python manage.py migrate
```

### 6. Тест податоци (опционално)

```bash
python manage.py add_test_data
```

### 7. Стартувај го серверот

```bash
python manage.py runserver
```

### ⚠️ Важно — Прв старт со AI модел

При прв старт, прогнозата може да биде генерирана со статистички модел. За да се вчита BiLSTM моделот, изврши:

```bash
python manage.py shell
```

```python
from airquality.models import Forecast
Forecast.objects.all().delete()
exit()
```

---

## ⚙️ Конфигурација

### Scheduler (автоматско освежување на секој час)

```bash
python manage.py runscheduler
```

---

## 🤖 AI Модел

Системот користи **Keras BiLSTM** (Bidirectional Long Short-Term Memory) невронска мрежа.

| Хоризонт | Директориум | Lookback | Излез |
|----------|-------------|----------|-------|
| 24 часа | `artifacts/24h/` | 48 записи | 24 предвидувања |
| 48 часа | `artifacts/48h/` | 48 записи | 24 предвидувања |
| 72 часа | `artifacts/72h/` | 48 записи | 24 предвидувања |

**Влезни карактеристики:** PM10, PM2.5, AQI, hour_sin/cos, day_sin/cos, diff features (14 вкупно)

**Fallback:** При недостаток на записи (<48) — линеарна регресија со сезонски корекции.

---

## 📡 API Endpoints

| Метод | URL | Опис |
|-------|-----|------|
| `GET` | `/api/current/` | Тековен запис |
| `GET` | `/api/history/?hours=24` | Историски записи |
| `GET` | `/api/forecast/` | Прогнози (JSON) |
| `GET` | `/api/refresh/` | Рачно освежување |
| `GET` | `/api/stations/` | Вредности по општини |
| `GET` | `/api/trends/?days=30` | Анализа на трендови |
| `GET` | `/api/unread-count/` | Непрочитани известувања |
| `GET` | `/api/ranking/?days=30` | Рангирање на денови |
| `GET` | `/api/compare/` | Споредба на два периоди |
| `POST` | `/api/regenerate-forecast/` | Избриши и регенерирај прогноза |
| `GET` | `/export/csv/?period=7d` | Извоз во CSV |
| `GET` | `/export/pdf/?period=7d` | Извоз во PDF |

---

## 🎨 AQI Скала

| AQI | Категорија | Боја |
|-----|-----------|------|
| 0–50 | Добар | 🟢 |
| 51–100 | Умерено | 🟡 |
| 101–150 | Нездрав за чувствителни | 🟠 |
| 151–200 | Нездрав | 🔴 |
| 201–300 | Многу нездрав | 🟣 |
| 301+ | Опасен | ⚫ |

---

## 🗄️ База на податоци

Апликацијата користи **PostgreSQL** хостирана на **Supabase**.

Главни табели:
- `airquality_airqualityrecord` — мерења (AQI, PM2.5, PM10, NO₂, CO, O₃, SO₂)
- `airquality_forecast` — AI прогнози
- `airquality_notification` — известувања
- `airquality_userprofile` — профил (праг, аватар, телефон)
- `airquality_savedlocation` — предефинирани локации
- `auth_user` — Django корисници

---

## 🏗️ Хостирање

| Сервис | Платформа |
|--------|-----------|
| Django Backend | [Render](https://render.com) |
| База на податоци | [Supabase](https://supabase.com) |
| Frontend | [Vercel](https://vercel.com) |

---

## 📦 Главни зависности

```
Django==5.0.6
tensorflow
requests
numpy / pandas / scikit-learn
django-apscheduler
reportlab
dj-database-url
psycopg2-binary
python-dotenv
Pillow
```

---

## 👥 Тим 20

| Член | Улога                  |
|------|------------------------|
| Пазаркоски Даниел | Project Manager        |
| Николов Горан | Backend Developer      |
| Николов Марио | Backend Developer      |
| Ташев Душан | Database Administrator |
| Србиноска Ана Марија | UI/UX Designer         |
| Блажевска Марија | Frontend Developer     |
| Ристова Радица | Frontend Developer     |
| Ахтаров Димитар | AI Engineer            |
| Јованчева Бојана | Technical Writer       |
| Чочороска Елеонора | QA Engineer            |

---

<div align="center">
  <sub>© 2026 Air Quality AI – Скопје | Тим 20 | Управување со ИКТ проекти</sub>
</div>