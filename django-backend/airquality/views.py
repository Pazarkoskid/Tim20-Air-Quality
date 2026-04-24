import csv
import io
import json
from datetime import timedelta
from collections import defaultdict
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from airquality.forms import HistoryFilterForm, ProfileForm, RegisterForm
from airquality.models import AirQualityRecord, Forecast, Notification, UserProfile
from airquality.services import fetch_air_quality, generate_forecast, save_record_and_notify


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

    since_24h = timezone.now() - timedelta(hours=24)
    chart_records = AirQualityRecord.objects.filter(timestamp__gte=since_24h).order_by('timestamp')
    chart_labels = [r.timestamp.strftime('%H:%M') for r in chart_records]
    chart_aqi    = [r.aqi for r in chart_records]
    chart_pm25   = [r.pm25 or 0 for r in chart_records]

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
    to = timezone.now()
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
                since = timezone.make_aware(timezone.datetime(df.year, df.month, df.day))
            if dt:
                to = timezone.make_aware(timezone.datetime(dt.year, dt.month, dt.day, 23, 59, 59))
            period_label = f'{df} – {dt}'

    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('timestamp')

    chart_labels = json.dumps([r.timestamp.strftime('%d.%m %H:%M') for r in records])
    chart_pm25   = json.dumps([r.pm25 or 0 for r in records])
    chart_pm10   = json.dumps([r.pm10 or 0 for r in records])
    chart_no2    = json.dumps([r.no2 or 0 for r in records])
    chart_co     = json.dumps([r.co or 0 for r in records])
    chart_aqi    = json.dumps([r.aqi for r in records])

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
#  Forecast / AI  (FIX #7 #10: regenerate daily, no freeze)
# ─────────────────────────────────────────────

@login_required
def forecast_view(request):
    now = timezone.now()

    # FIX #7 & #10: Delete stale forecasts (generated before start of today)
    # so they regenerate fresh every day with correct dates
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stale = Forecast.objects.filter(generated_at__lt=today_start)
    if stale.exists():
        stale.delete()

    forecasts = Forecast.objects.filter(
        forecast_time__gte=now  # only future forecasts
    ).order_by('hours_ahead')

    model_used = None
    if not forecasts.exists():
        result = generate_forecast()
        if isinstance(result, tuple):
            _, model_used = result
        forecasts = Forecast.objects.filter(forecast_time__gte=now).order_by('hours_ahead')

    if not model_used:
        model_used = 'статистички модел'

    labels     = json.dumps([f.forecast_time.strftime('%d.%m %H:%M') for f in forecasts])
    pred_aqi   = json.dumps([f.predicted_aqi for f in forecasts])
    pred_pm25  = json.dumps([f.predicted_pm25 or 0 for f in forecasts])
    confidence = json.dumps([f.confidence for f in forecasts])

    # Snap at +24h, +48h, +72h from now
    snap24 = forecasts.filter(hours_ahead__lte=24).last()
    snap48 = forecasts.filter(hours_ahead__gt=24, hours_ahead__lte=48).last()
    snap72 = forecasts.filter(hours_ahead__gt=48, hours_ahead__lte=72).last()

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
        'model_used': model_used,
        'forecast_date': now,
    })


# ─────────────────────────────────────────────
#  Notifications  (FIX #1 #3 #9)
# ─────────────────────────────────────────────

@login_required
def notifications_view(request):
    notifs = Notification.objects.filter(user=request.user)
    notifs.filter(read=False).update(read=True)

    # FIX #3: push notifications — get latest AQI for dynamic recommendations
    latest = AirQualityRecord.objects.first()
    aqi_now = latest.aqi if latest else 0

    return render(request, 'airquality/notifications.html', {
        'notifications': notifs,
        'unread_count': 0,
        'aqi_now': aqi_now,
    })


@login_required
@require_POST
def mark_all_read(request):
    # FIX #1: was failing silently — ensure correct CSRF and method
    Notification.objects.filter(user=request.user, read=False).update(read=True)
    return JsonResponse({'status': 'ok'})


# FIX #9: delete single notification
@login_required
@require_POST
def delete_notification(request, pk):
    Notification.objects.filter(user=request.user, pk=pk).delete()
    return JsonResponse({'status': 'ok'})


# FIX #9: delete all notifications
@login_required
@require_POST
def delete_all_notifications(request):
    Notification.objects.filter(user=request.user).delete()
    return JsonResponse({'status': 'ok'})


# ─────────────────────────────────────────────
#  API: unread notification count (for polling)
# ─────────────────────────────────────────────

@login_required
def api_unread_count(request):
    count = Notification.objects.filter(user=request.user, read=False).count()
    return JsonResponse({'unread_count': count})


# ─────────────────────────────────────────────
#  Settings / Profile  (FIX #4 #5 #8)
# ─────────────────────────────────────────────

@login_required
def settings_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, instance=profile,
                       initial={'first_name': request.user.first_name,
                                'last_name': request.user.last_name,
                                'email': request.user.email})

    if request.method == 'POST':
        action = request.POST.get('action', 'profile')

        # FIX #8: change_password — use messages.add_message directly, no double message
        if action == 'change_password':
            new_pw  = request.POST.get('new_password', '').strip()
            confirm = request.POST.get('confirm_password', '').strip()
            if not new_pw:
                messages.error(request, 'Внесете нова лозинка.')
            elif new_pw != confirm:
                messages.error(request, 'Лозинките не се совпаѓаат.')
            elif len(new_pw) < 8:
                messages.error(request, 'Лозинката мора да биде најмалку 8 знаци.')
            else:
                request.user.set_password(new_pw)
                request.user.save()
                update_session_auth_hash(request, request.user)
                # FIX #8: use storage.used flag workaround — add only once
                # by clearing existing success messages first
                storage = messages.get_messages(request)
                storage.used = True
                messages.success(request, '✅ Лозинката е успешно променета.')
            return redirect('settings')

        # FIX #4: profile save — save User fields + UserProfile fields directly
        if action == 'profile':
            first_name = request.POST.get('first_name', '').strip()
            last_name  = request.POST.get('last_name', '').strip()
            email      = request.POST.get('email', '').strip()
            request.user.first_name = first_name
            request.user.last_name  = last_name
            if email:
                request.user.email = email
            request.user.save()

            # Save UserProfile fields directly — do not rely on form.is_valid()
            # because extra fields (first_name/last_name) cause validation issues
            try:
                profile.aqi_threshold         = int(request.POST.get('aqi_threshold', profile.aqi_threshold))
            except (ValueError, TypeError):
                pass
            profile.notifications_enabled = request.POST.get('notifications_enabled') == 'on'
            profile.notify_email           = request.POST.get('notify_email') == 'on'
            profile.notify_push            = request.POST.get('notify_push') == 'on'
            profile.save()

            messages.success(request, 'Поставките се зачувани.')
            return redirect('settings')

    unread_count = Notification.objects.filter(user=request.user, read=False).count()
    return render(request, 'airquality/settings.html', {
        'form': form, 'profile': profile, 'unread_count': unread_count
    })


# ─────────────────────────────────────────────
#  Export CSV  (FIX #2: respect period param)
# ─────────────────────────────────────────────

@login_required
def export_csv(request):
    # FIX #2: use same period logic as history_view
    period = request.GET.get('period', '7d')
    now = timezone.now()

    if period == '24h':
        since = now - timedelta(hours=24)
        label = 'poslednite_24_chasa'
    elif period == '30d':
        since = now - timedelta(days=30)
        label = 'poslednite_30_dena'
    elif period == 'custom':
        date_from = request.GET.get('date_from')
        date_to   = request.GET.get('date_to')
        try:
            from datetime import datetime as dt_
            since = timezone.make_aware(dt_.strptime(date_from, '%Y-%m-%d'))
            to    = timezone.make_aware(dt_.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
        except Exception:
            since = now - timedelta(days=7)
            to    = now
        label = f'{date_from}_do_{date_to}'
    else:  # default 7d
        since = now - timedelta(days=7)
        label = 'poslednite_7_dena'

    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('-timestamp')

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="kvalitet_vozduh_{label}.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Датум/Време', 'AQI', 'PM2.5 (µg/m³)', 'PM10 (µg/m³)',
                     'CO (µg/m³)', 'NO2 (µg/m³)', 'O3 (µg/m³)', 'SO2 (µg/m³)',
                     'NH3 (µg/m³)', 'Извор'])
    for r in records:
        writer.writerow([
            r.timestamp.strftime('%d.%m.%Y %H:%M'),
            f'{r.aqi:.1f}',
            f'{r.pm25:.2f}' if r.pm25 is not None else '',
            f'{r.pm10:.2f}' if r.pm10 is not None else '',
            f'{r.co:.2f}'   if r.co   is not None else '',
            f'{r.no2:.2f}'  if r.no2  is not None else '',
            f'{r.o3:.2f}'   if r.o3   is not None else '',
            f'{r.so2:.2f}'  if r.so2  is not None else '',
            f'{r.nh3:.2f}'  if r.nh3  is not None else '',
            r.source,
        ])
    return response


# ─────────────────────────────────────────────
#  Export PDF  (FIX #2: respect period param)
# ─────────────────────────────────────────────

@login_required
def export_pdf(request):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return HttpResponse("reportlab not installed", status=500)

    import os as _os
    _BASE = _os.path.dirname(_os.path.abspath(__file__))
    _FONT_SEARCH = [
        _os.path.join(_BASE, 'static', 'fonts'),
        _os.path.join(_BASE, '..', 'static', 'fonts'),
        '/usr/share/fonts/truetype/dejavu/',
        '/usr/share/fonts/dejavu/',
    ]
    FONT = 'Helvetica'
    FONT_BOLD = 'Helvetica-Bold'
    for _d in _FONT_SEARCH:
        _reg  = _os.path.join(_d, 'DejaVuSans.ttf')
        _bold = _os.path.join(_d, 'DejaVuSans-Bold.ttf')
        if _os.path.exists(_reg) and _os.path.exists(_bold):
            try:
                if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('DejaVu', _reg))
                    pdfmetrics.registerFont(TTFont('DejaVu-Bold', _bold))
                FONT = 'DejaVu'
                FONT_BOLD = 'DejaVu-Bold'
            except Exception:
                pass
            break

    # FIX #2: respect period query param
    period = request.GET.get('period', '7d')
    now = timezone.now()
    if period == '24h':
        since = now - timedelta(hours=24)
        period_label = 'Последни 24 часа'
    elif period == '30d':
        since = now - timedelta(days=30)
        period_label = 'Последни 30 дена'
    elif period == 'custom':
        date_from = request.GET.get('date_from')
        date_to   = request.GET.get('date_to')
        try:
            from datetime import datetime as dt_
            since = timezone.make_aware(dt_.strptime(date_from, '%Y-%m-%d'))
            period_label = f'{date_from} – {date_to}'
        except Exception:
            since = now - timedelta(days=7)
            period_label = 'Последни 7 дена'
    else:
        since = now - timedelta(days=7)
        period_label = 'Последни 7 дена'

    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('-timestamp')[:200]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=36)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('MkTitle', fontName=FONT_BOLD, fontSize=16,
                                  textColor=colors.HexColor('#1a6b8a'), spaceAfter=4)
    normal_style = ParagraphStyle('MkNormal', fontName=FONT, fontSize=9,
                                   textColor=colors.HexColor('#555555'), spaceAfter=8)
    header_cell = ParagraphStyle('MkHeader', fontName=FONT_BOLD, fontSize=8,
                                  textColor=colors.white, leading=10)
    data_cell   = ParagraphStyle('MkCell', fontName=FONT, fontSize=8,
                                  textColor=colors.HexColor('#222222'), leading=10)

    mk_headers = ['Датум/Време', 'AQI', 'PM2.5', 'PM10', 'NO2', 'CO']
    data = [[Paragraph(h, header_cell) for h in mk_headers]]
    for r in records:
        data.append([
            Paragraph(r.timestamp.strftime('%d.%m.%Y %H:%M'), data_cell),
            Paragraph(f'{r.aqi:.1f}', data_cell),
            Paragraph(f'{r.pm25:.2f}' if r.pm25 else '–', data_cell),
            Paragraph(f'{r.pm10:.2f}' if r.pm10 else '–', data_cell),
            Paragraph(f'{r.no2:.2f}'  if r.no2  else '–', data_cell),
            Paragraph(f'{r.co:.2f}'   if r.co   else '–', data_cell),
        ])

    elements = []
    elements.append(Paragraph('Квалитет на воздух – Скопје', title_style))
    elements.append(Paragraph(
        f'Извештај генериран: {now.strftime("%d.%m.%Y %H:%M")}  |  Период: {period_label}',
        normal_style
    ))
    elements.append(Spacer(1, 10))

    col_widths = [115, 45, 60, 60, 60, 60]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), colors.HexColor('#1a6b8a')),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f7fa')]),
        ('GRID',          (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('ALIGN',         (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(table)
    doc.build(elements)

    buf.seek(0)
    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="izvestaj_kvalitet_vozduh.pdf"'
    return response


# ─────────────────────────────────────────────
#  Import CSV
# ─────────────────────────────────────────────

@login_required
def import_csv(request):
    if request.method == 'POST' and request.FILES.get('csv_file'):
        f = request.FILES['csv_file']
        decoded = f.read().decode('utf-8-sig').splitlines()
        reader = csv.DictReader(decoded)
        count = 0
        for row in reader:
            try:
                AirQualityRecord.objects.create(
                    timestamp=row.get('Timestamp') or row.get('Датум/Време') or timezone.now(),
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



# ─────────────────────────────────────────────
#  CR-002: Ranking table — best/worst days
# ─────────────────────────────────────────────

@login_required
def api_ranking(request):
    """Return top 10 worst + top 10 best days by average AQI."""
    days = int(request.GET.get('days', 30))
    since = timezone.now() - timedelta(days=days)
    records = AirQualityRecord.objects.filter(timestamp__gte=since).order_by('timestamp')

    daily = defaultdict(list)
    for r in records:
        day_key = r.timestamp.strftime('%Y-%m-%d')
        daily[day_key].append({'aqi': r.aqi, 'pm25': r.pm25 or 0})

    results = []
    for day, vals in sorted(daily.items()):
        avg_aqi  = round(sum(v['aqi'] for v in vals) / len(vals), 1)
        max_pm25 = round(max(v['pm25'] for v in vals), 2)
        if avg_aqi > 150:   category, color = 'Нездраво', '#e05050'
        elif avg_aqi > 100: category, color = 'Чувствително', '#f0884a'
        elif avg_aqi > 50:  category, color = 'Умерено', '#f5c542'
        else:               category, color = 'Добро', '#3fb68b'
        results.append({'date': day, 'avg_aqi': avg_aqi, 'max_pm25': max_pm25,
                        'category': category, 'color': color, 'count': len(vals)})

    results.sort(key=lambda x: x['avg_aqi'], reverse=True)
    return JsonResponse({'worst': results[:10], 'best': results[-10:][::-1]})


# ─────────────────────────────────────────────
#  CR-003: Compare two periods
# ─────────────────────────────────────────────

@login_required
def api_compare(request):
    """Compare AQI between two date ranges, normalized to hours 0-N."""
    from_1 = request.GET.get('from1')
    to_1   = request.GET.get('to1')
    from_2 = request.GET.get('from2')
    to_2   = request.GET.get('to2')

    from datetime import datetime as dt_
    def parse(s): return timezone.make_aware(dt_.strptime(s, '%Y-%m-%d'))

    try:
        s1 = parse(from_1); e1 = parse(to_1).replace(hour=23, minute=59, second=59)
        s2 = parse(from_2); e2 = parse(to_2).replace(hour=23, minute=59, second=59)
    except Exception:
        return JsonResponse({'error': 'Invalid dates'}, status=400)

    def fetch_series(start, end):
        recs = AirQualityRecord.objects.filter(
            timestamp__gte=start, timestamp__lte=end
        ).order_by('timestamp')
        hours_map = defaultdict(list)
        for r in recs:
            h = int((r.timestamp - start).total_seconds() // 3600)
            hours_map[h].append(r.aqi)
        if not hours_map:
            return [], []
        max_h = max(hours_map.keys())
        labels = list(range(max_h + 1))
        values = [round(sum(hours_map[h]) / len(hours_map[h]), 1) if h in hours_map else None
                  for h in labels]
        return labels, values

    l1, v1 = fetch_series(s1, e1)
    l2, v2 = fetch_series(s2, e2)

    return JsonResponse({
        'period1': {'label': f'{from_1} – {to_1}', 'labels': l1, 'values': v1},
        'period2': {'label': f'{from_2} – {to_2}', 'labels': l2, 'values': v2},
    })

@login_required
def api_refresh(request):
    data = fetch_air_quality()
    record = save_record_and_notify(data)
    unread_count = Notification.objects.filter(user=request.user, read=False).count()
    return JsonResponse({
        'status': 'ok',
        'record': record.to_dict(),
        'unread_count': unread_count,
    })
