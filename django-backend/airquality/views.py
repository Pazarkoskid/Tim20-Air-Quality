import csv
import io
import json
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from airquality.forms import HistoryFilterForm, ProfileForm, RegisterForm
from airquality.models import AirQualityRecord, Forecast, Notification, UserProfile
from airquality.services import fetch_air_quality, generate_forecast, save_record_and_notify
from django.shortcuts import render
from .models import AirQualityRecord, Notification


# ─────────────────────────────────────────────
#  Auth
# ─────────────────────────────────────────────

def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Регистрацијата е успешна! Добредојдовте.')
        return redirect('dashboard')
    return render(request, 'airquality/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'airquality/login.html')


# ─────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────

@login_required
def dashboard(request):
    latest = AirQualityRecord.objects.first()
    if not latest:
        data = fetch_air_quality()
        latest = save_record_and_notify(data)

    # Last 24h chart data
    since_24h = timezone.now() - timedelta(hours=24)
    chart_records = AirQualityRecord.objects.filter(timestamp__gte=since_24h).order_by('timestamp')
    chart_labels = [r.timestamp.strftime('%H:%M') for r in chart_records]
    chart_aqi = [r.aqi for r in chart_records]
    chart_pm25 = [r.pm25 or 0 for r in chart_records]

    # 72h forecast summary (24h/48h/72h averages)
    forecasts_24 = Forecast.objects.filter(hours_ahead__lte=24).order_by('hours_ahead')
    forecasts_48 = Forecast.objects.filter(hours_ahead__gt=24, hours_ahead__lte=48).order_by('hours_ahead')
    forecasts_72 = Forecast.objects.filter(hours_ahead__gt=48, hours_ahead__lte=72).order_by('hours_ahead')

    def avg_aqi(qs):
        vals = [f.predicted_aqi for f in qs if f.predicted_aqi]
        return round(sum(vals) / len(vals), 1) if vals else None

    unread_count = Notification.objects.filter(user=request.user, read=False).count()

    context = {
        'latest': latest,
        'aqi_label': latest.aqi_label() if latest else ('N/A', 'good'),
        'chart_labels': json.dumps(chart_labels),
        'chart_aqi': json.dumps(chart_aqi),
        'chart_pm25': json.dumps(chart_pm25),
        'forecast_24': avg_aqi(forecasts_24),
        'forecast_48': avg_aqi(forecasts_48),
        'forecast_72': avg_aqi(forecasts_72),
        'unread_count': unread_count,
    }
    return render(request, 'airquality/dashboard.html', context)


# ─────────────────────────────────────────────
#  Map
# ─────────────────────────────────────────────
@login_required
def map_view(request):
    latest = AirQualityRecord.objects.first()
    unread_count = Notification.objects.filter(user=request.user, read=False).count()

    context = {
        'latest': latest,
        'unread_count': unread_count,
        'openweather_key': settings.OPENWEATHER_API_KEY,
        'city_lat': settings.CITY_LAT,
        'city_lon': settings.CITY_LON,
        'city_name': settings.CITY_NAME,
    }

    return render(request, 'airquality/map.html', context)


# ─────────────────────────────────────────────
#  History
# ─────────────────────────────────────────────

@login_required
def history_view(request):
    form = HistoryFilterForm(request.GET or None)
    since = timezone.now() - timedelta(hours=24)
    period_label = 'Последни 24 часа'

    if form.is_valid():
        period = form.cleaned_data.get('period', '24h')
        if period == '7d':
            since = timezone.now() - timedelta(days=7)
            period_label = 'Последни 7 дена'
        elif period == '30d':
            since = timezone.now() - timedelta(days=30)
            period_label = 'Последни 30 дена'
        elif period == 'custom':
            df = form.cleaned_data.get('date_from')
            dt = form.cleaned_data.get('date_to')
            if df:
                since = timezone.make_aware(
                    timezone.datetime(df.year, df.month, df.day))
            if dt:
                to = timezone.make_aware(
                    timezone.datetime(dt.year, dt.month, dt.day, 23, 59, 59))
            else:
                to = timezone.now()
            period_label = f'{df} – {dt}'

    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('timestamp')
    if 'to' not in dir():
        to = timezone.now()

    chart_labels = json.dumps([r.timestamp.strftime('%d.%m %H:%M') for r in records])
    chart_pm25 = json.dumps([r.pm25 or 0 for r in records])
    chart_pm10 = json.dumps([r.pm10 or 0 for r in records])
    chart_no2 = json.dumps([r.no2 or 0 for r in records])
    chart_co = json.dumps([r.co or 0 for r in records])
    chart_aqi = json.dumps([r.aqi for r in records])

    unread_count = Notification.objects.filter(user=request.user, read=False).count()

    return render(request, 'airquality/history.html', {
        'form': form,
        'records': records[:200],
        'total': records.count(),
        'period_label': period_label,
        'chart_labels': chart_labels,
        'chart_pm25': chart_pm25,
        'chart_pm10': chart_pm10,
        'chart_no2': chart_no2,
        'chart_co': chart_co,
        'chart_aqi': chart_aqi,
        'unread_count': unread_count,
    })


# ─────────────────────────────────────────────
#  Forecast / AI
# ─────────────────────────────────────────────

@login_required
def forecast_view(request):
    forecasts = Forecast.objects.filter(
        hours_ahead__in=list(range(1, 73))
    ).order_by('hours_ahead')

    if not forecasts.exists():
        generate_forecast()
        forecasts = Forecast.objects.order_by('hours_ahead')

    labels = json.dumps([f.forecast_time.strftime('%d.%m %H:%M') for f in forecasts])
    pred_aqi = json.dumps([f.predicted_aqi for f in forecasts])
    pred_pm25 = json.dumps([f.predicted_pm25 or 0 for f in forecasts])
    confidence = json.dumps([f.confidence for f in forecasts])

    # Key forecast snapshots
    snap24 = forecasts.filter(hours_ahead=24).first()
    snap48 = forecasts.filter(hours_ahead=48).first()
    snap72 = forecasts.filter(hours_ahead=72).first()

    unread_count = Notification.objects.filter(user=request.user, read=False).count()
    return render(request, 'airquality/forecast.html', {
        'forecasts': forecasts,
        'labels': labels,
        'pred_aqi': pred_aqi,
        'pred_pm25': pred_pm25,
        'confidence': confidence,
        'snap24': snap24,
        'snap48': snap48,
        'snap72': snap72,
        'unread_count': unread_count,
    })


# ─────────────────────────────────────────────
#  Notifications
# ─────────────────────────────────────────────

@login_required
def notifications_view(request):
    notifs = Notification.objects.filter(user=request.user)
    notifs.filter(read=False).update(read=True)
    return render(request, 'airquality/notifications.html', {
        'notifications': notifs,
        'unread_count': 0,
    })


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, read=False).update(read=True)
    return JsonResponse({'status': 'ok'})


# ─────────────────────────────────────────────
#  Settings / Profile
# ─────────────────────────────────────────────

@login_required
def settings_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, instance=profile,
                       initial={'first_name': request.user.first_name,
                                'last_name': request.user.last_name,
                                'email': request.user.email})
    if request.method == 'POST' and form.is_valid():
        request.user.first_name = form.cleaned_data['first_name']
        request.user.last_name = form.cleaned_data['last_name']
        request.user.email = form.cleaned_data['email']
        request.user.save()
        form.save()
        messages.success(request, 'Поставките се зачувани.')
        return redirect('settings')
    unread_count = Notification.objects.filter(user=request.user, read=False).count()
    return render(request, 'airquality/settings.html', {
        'form': form, 'profile': profile, 'unread_count': unread_count
    })


# ─────────────────────────────────────────────
#  Export CSV
# ─────────────────────────────────────────────

@login_required
def export_csv(request):
    since = timezone.now() - timedelta(days=30)
    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('-timestamp')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="air_quality_skopje.csv"'
    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'AQI', 'PM2.5', 'PM10', 'CO', 'NO2', 'O3', 'SO2', 'NH3', 'Source'])
    for r in records:
        writer.writerow([r.timestamp, r.aqi, r.pm25, r.pm10, r.co, r.no2, r.o3, r.so2, r.nh3, r.source])
    return response


# ─────────────────────────────────────────────
#  Export PDF
# ─────────────────────────────────────────────

@login_required
def export_pdf(request):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        return HttpResponse("reportlab not installed", status=500)

    since = timezone.now() - timedelta(days=7)
    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('-timestamp')[:100]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph('Air Quality AI – Скопје', styles['Title']))
    elements.append(Paragraph(f'Извештај генериран: {timezone.now().strftime("%d.%m.%Y %H:%M")}', styles['Normal']))
    elements.append(Spacer(1, 12))

    data = [['Timestamp', 'AQI', 'PM2.5', 'PM10', 'NO2', 'CO']]
    for r in records:
        data.append([
            r.timestamp.strftime('%d.%m.%Y %H:%M'),
            f'{r.aqi:.1f}',
            f'{r.pm25:.2f}' if r.pm25 else '-',
            f'{r.pm10:.2f}' if r.pm10 else '-',
            f'{r.no2:.2f}' if r.no2 else '-',
            f'{r.co:.2f}' if r.co else '-',
        ])

    table = Table(data, colWidths=[120, 50, 60, 60, 60, 60])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a6b8a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f7fa')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(table)
    doc.build(elements)

    buf.seek(0)
    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="air_quality_report.pdf"'
    return response


# ─────────────────────────────────────────────
#  Import CSV
# ─────────────────────────────────────────────

@login_required
def import_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        f = request.FILES['csv_file']
        decoded = f.read().decode('utf-8').splitlines()
        reader = csv.DictReader(decoded)
        count = 0
        for row in reader:
            try:
                AirQualityRecord.objects.create(
                    timestamp=row.get('Timestamp') or timezone.now(),
                    aqi=float(row.get('AQI', 0)),
                    pm25=float(row['PM2.5']) if row.get('PM2.5') else None,
                    pm10=float(row['PM10']) if row.get('PM10') else None,
                    co=float(row['CO']) if row.get('CO') else None,
                    no2=float(row['NO2']) if row.get('NO2') else None,
                    o3=float(row['O3']) if row.get('O3') else None,
                    source='import',
                )
                count += 1
            except Exception:
                pass
        messages.success(request, f'Успешно увезени {count} записи.')
    return redirect('history')


# ─────────────────────────────────────────────
#  API endpoints (JSON)
# ─────────────────────────────────────────────

@login_required
def api_current(request):
    record = AirQualityRecord.objects.first()
    if not record:
        data = fetch_air_quality()
        record = save_record_and_notify(data)
    return JsonResponse(record.to_dict())


@login_required
def api_history(request):
    hours = int(request.GET.get('hours', 24))
    since = timezone.now() - timedelta(hours=hours)
    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('timestamp')
    return JsonResponse({'records': [r.to_dict() for r in records]})


@login_required
def api_forecast(request):
    forecasts = Forecast.objects.order_by('hours_ahead')
    return JsonResponse({'forecasts': [f.to_dict() for f in forecasts]})


@login_required
def api_refresh(request):
    """Manually trigger a data fetch."""
    data = fetch_air_quality()
    record = save_record_and_notify(data)
    return JsonResponse({'status': 'ok', 'record': record.to_dict()})
