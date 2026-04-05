# 🌬 Air Quality AI – Скопје

Интелигентен Django веб систем за следење, анализа и предвидување на квалитетот на воздухот во Скопје. Дел од концептот „Паметен и безбеден град".

---

## 📋 Содржина на проектот

```
air_quality_django/
├── core/                        # Django project config
│   ├── settings.py              # Главни поставки
│   ├── urls.py                  # Корен URL routing
│   └── wsgi.py
├── airquality/                  # Главна апликација
│   ├── models.py                # БД модели (AirQualityRecord, Forecast, Notification, UserProfile)
│   ├── views.py                 # Сите views (dashboard, map, history, forecast, notifications, settings, export/import)
│   ├── services.py              # OpenWeather API + mock fallback + AI forecasting
│   ├── urls.py                  # URL patterns
│   ├── forms.py                 # Django forms (Register, Profile, HistoryFilter)
│   ├── admin.py                 # Admin панел регистрација
│   ├── signals.py               # Auto-create UserProfile
│   ├── apps.py                  # AppConfig
│   ├── templates/airquality/    # Сите HTML templates
│   │   ├── base.html            # Sidebar + topbar layout
│   │   ├── login.html           # Страница за најава
│   │   ├── register.html        # Страница за регистрација
│   │   ├── dashboard.html       # Главна контролна табла + AQI + Charts
│   │   ├── map.html             # Leaflet.js интерактивна мапа
│   │   ├── history.html         # Историски податоци + филтри + export
│   │   ├── forecast.html        # AI прогноза 24/48/72 часа
│   │   ├── notifications.html   # Известувања и AI препораки
│   │   └── settings.html        # Профил и кориснички поставки
│   └── management/commands/
│       └── runscheduler.py      # APScheduler за автоматско ажурирање
├── manage.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## ⚙️ Инсталација и стартување

### 1. Клонирај го репото

```bash
git clone https://github.com/Pazarkoskid/Tim20-Air-Quality.git
cd Tim20-Air-Quality
```

### 2. Создај и активирај виртуелна средина

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Инсталирај ги зависностите

```bash
pip install -r requirements.txt
```

### 4. Постави `.env` фајл

```bash
cp .env.example .env
```

Отвори `.env` и постави ги вредностите:

```env
SECRET_KEY=some-random-secret-key-here
DEBUG=True
OPENWEATHER_API_KEY=твојот_клуч_од_openweathermap.org
ALLOWED_HOSTS=localhost,127.0.0.1
```

> **Добивање на OpenWeather API клуч:**
> Регистрирај се на [openweathermap.org](https://openweathermap.org/) → My API Keys → Create key.
> Апликацијата функционира и **без** клуч — во тој случај автоматски се користат реалистични mock податоци за Скопје.

### 5. Направи миграции и иницијализирај ја базата

```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Создај superuser (admin)

```bash
python manage.py createsuperuser
```

### 7. Стартувај го серверот

```bash
python manage.py runserver
```

Отвори го прелистувачот на: **http://127.0.0.1:8000**

---

## 🔄 Автоматско ажурирање на податоци (Scheduler)

За да се ажурираат податоците автоматски на секој час, стартувај го scheduler-от во посебен терминал:

```bash
python manage.py runscheduler
```

Ова ги извршува следните задачи:
- **На секој час (`:00`)** — зема live податоци од OpenWeather или mock и ги зачувува во базата
- **На секои 6 часа** — генерира AI прогнози за следните 72 часа

---

## 🌐 URL структура

| URL | Опис |
|-----|------|
| `/` | Редирект кон dashboard |
| `/login/` | Страница за најава |
| `/register/` | Страница за регистрација |
| `/dashboard/` | Главна контролна табла |
| `/map/` | Интерактивна Leaflet.js мапа |
| `/history/` | Историски податоци со филтри |
| `/forecast/` | AI прогноза 24/48/72 часа |
| `/notifications/` | Известувања и препораки |
| `/settings/` | Профил и поставки |
| `/export/csv/` | Извоз на CSV (последни 30 дена) |
| `/export/pdf/` | Извоз на PDF извештај |
| `/import/csv/` | Увоз на CSV податоци |
| `/api/current/` | JSON — моментален запис |
| `/api/history/?hours=24` | JSON — историски записи |
| `/api/forecast/` | JSON — прогнози |
| `/api/refresh/` | Рачно освежување на податоци |
| `/admin/` | Django admin панел |

---

## 🏗 Функционалности

### ✅ Имплементирано

| # | Барање | Статус |
|---|--------|--------|
| 1 | Прибирање податоци преку OpenWeather Air Pollution API | ✅ |
| 2 | Периодично ажурирање (hourly scheduler) | ✅ |
| 3 | Складирање на PM2.5, PM10, CO, NO2, O3, SO2, NH3 | ✅ |
| 4 | Историски податоци во SQLite база | ✅ |
| 5 | Export во CSV | ✅ |
| 6 | Export во PDF (ReportLab) | ✅ |
| 7 | Import на CSV | ✅ |
| 8 | Приказ на тековен AQI | ✅ |
| 9 | Визуелизација преку Chart.js | ✅ |
| 10 | Приказ на Leaflet.js мапа со станици | ✅ |
| 11 | Преглед на историски податоци со филтри | ✅ |
| 12 | AI модел за предвидување (линеарна регресија + сезонски корекции) | ✅ |
| 13 | Прогнози за 24/48/72 часа | ✅ |
| 14 | Анализа на трендови | ✅ |
| 15 | Нотификации при надминување на праг | ✅ |
| 16 | AI препораки за корисниците | ✅ |
| 17 | Регистрација на корисници | ✅ |
| 18 | Автентикација (логирање) | ✅ |
| 19 | Персонализирани поставки | ✅ |

---

## 🛠 Технологии

| Компонента | Технологија |
|-----------|-------------|
| Backend | Django 5.0 |
| База на податоци | SQLite (лесно менлив на PostgreSQL) |
| Scheduler | APScheduler + django-apscheduler |
| Charts | Chart.js 4 |
| Мapа | Leaflet.js |
| PDF Export | ReportLab |
| AI/ML | NumPy, Pandas, scikit-learn |
| Надворешно API | OpenWeather Air Pollution API |
| Frontend стил | Custom CSS (Dark theme) |

---

## 🔐 Безбедност

- Лозинките се шифрираат со `PBKDF2PasswordHasher` (Django default)
- CSRF заштита на сите POST форми
- Сите views бараат `@login_required`
- `.env` фајлот **не е** во git (додаден во `.gitignore`)

---

## 📦 Производствено деплојување

За production, промени го `.env`:

```env
DEBUG=False
SECRET_KEY=силна-случајна-лозинка
ALLOWED_HOSTS=твојот-домен.mk
```

И стартувај со Gunicorn:

```bash
pip install gunicorn
gunicorn core.wsgi:application --bind 0.0.0.0:8000
```

---

## 👥 Тим 20

Проект за предметот **Управување со ИКТ проекти**  
Тема: **Air Quality AI – Скопје**
