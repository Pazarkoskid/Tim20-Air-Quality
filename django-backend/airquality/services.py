"""
services.py — Data fetching, mock fallback, and AI forecasting
"""

import random
import math
import logging
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  AQI helper (OpenWeather uses 1-5 scale)
# ─────────────────────────────────────────────

OW_AQI_MAP = {1: 25, 2: 75, 3: 125, 4: 175, 5: 250}


def ow_aqi_to_index(ow_aqi: int, pm25: float) -> float:
    """Convert OpenWeather AQI (1-5) to a US-style 0-500 AQI using pm2.5."""
    if pm25 is None:
        return float(OW_AQI_MAP.get(ow_aqi, 100))
    # Simple linear mapping for PM2.5 breakpoints (US EPA)
    breakpoints = [
        (0.0,   12.0,  0,   50),
        (12.1,  35.4,  51,  100),
        (35.5,  55.4,  101, 150),
        (55.5,  150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ]
    for lo_c, hi_c, lo_i, hi_i in breakpoints:
        if lo_c <= pm25 <= hi_c:
            aqi = ((hi_i - lo_i) / (hi_c - lo_c)) * (pm25 - lo_c) + lo_i
            return round(aqi, 1)
    return min(500.0, pm25)


# ─────────────────────────────────────────────
#  Fetch live data from OpenWeather
# ─────────────────────────────────────────────

def fetch_air_quality():
    """
    Fetch current air quality from OpenWeather Air Pollution API.
    Returns a dict ready to create an AirQualityRecord, or None on failure.
    """
    api_key = settings.OPENWEATHER_API_KEY
    if not api_key:
        logger.warning("No OPENWEATHER_API_KEY set — using mock data.")
        return get_mock_data()

    url = (
        f"http://api.openweathermap.org/data/2.5/air_pollution"
        f"?lat={settings.CITY_LAT}&lon={settings.CITY_LON}&appid={api_key}"
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        comp = data['list'][0]['components']
        ow_aqi = data['list'][0]['main']['aqi']
        pm25 = comp.get('pm2_5')
        aqi = ow_aqi_to_index(ow_aqi, pm25)
        return {
            'aqi': aqi,
            'pm25': pm25,
            'pm10': comp.get('pm10'),
            'co': comp.get('co'),
            'no2': comp.get('no2'),
            'o3': comp.get('o3'),
            'so2': comp.get('so2'),
            'nh3': comp.get('nh3'),
            'source': 'openweather',
        }
    except Exception as exc:
        logger.error("OpenWeather API error: %s — falling back to mock data.", exc)
        return get_mock_data()


# ─────────────────────────────────────────────
#  Mock / fallback data (realistic Skopje range)
# ─────────────────────────────────────────────

def get_mock_data():
    hour = datetime.now().hour
    # Simulate morning/evening rush-hour peaks
    base_pm25 = 20 + 30 * math.exp(-((hour - 8) ** 2) / 18) + \
                     25 * math.exp(-((hour - 19) ** 2) / 18) + \
                     random.gauss(0, 5)
    base_pm25 = max(2, base_pm25)
    aqi = ow_aqi_to_index(None, base_pm25)
    return {
        'aqi': round(aqi, 1),
        'pm25': round(base_pm25, 2),
        'pm10': round(base_pm25 * 1.8 + random.gauss(0, 3), 2),
        'co': round(200 + random.gauss(0, 20), 2),
        'no2': round(15 + random.gauss(0, 5), 2),
        'o3': round(60 + random.gauss(0, 10), 2),
        'so2': round(5 + random.gauss(0, 2), 2),
        'nh3': round(3 + random.gauss(0, 1), 2),
        'source': 'mock',
    }


# ─────────────────────────────────────────────
#  Save record + trigger notifications
# ─────────────────────────────────────────────

def save_record_and_notify(data: dict):
    from airquality.models import AirQualityRecord, UserProfile, Notification
    from django.contrib.auth.models import User

    record = AirQualityRecord(**data)
    record.save()
    logger.info("Saved AirQualityRecord id=%s aqi=%.1f source=%s", record.id, record.aqi, record.source)

    # Check notification thresholds
    profiles = UserProfile.objects.filter(notifications_enabled=True)
    for profile in profiles:
        if record.aqi >= profile.aqi_threshold:
            label, _ = record.aqi_label()
            msg = (
                f"⚠️ Нивото на загаденост е {label} (AQI {record.aqi:.0f}). "
                f"PM2.5: {record.pm25} µg/m³. Препорачуваме да останете на затворено."
            )
            Notification.objects.create(
                user=profile.user,
                message=msg,
                aqi_value=record.aqi,
            )
    return record


# ─────────────────────────────────────────────
#  AI Forecasting (linear trend + seasonality)
# ─────────────────────────────────────────────

def generate_forecast():
    """
    Generate 24/48/72-hour forecasts using a simple linear regression
    on the last 72 hours of historical data with hour-of-day seasonality.
    """
    from airquality.models import AirQualityRecord, Forecast

    cutoff = timezone.now() - timedelta(hours=72)
    records = AirQualityRecord.objects.filter(timestamp__gte=cutoff).order_by('timestamp')

    if records.count() < 5:
        logger.warning("Not enough data for forecasting — using mock projection.")
        records_data = None
    else:
        records_data = list(records.values('timestamp', 'aqi', 'pm25', 'pm10'))

    now = timezone.now()
    # Delete old forecasts
    Forecast.objects.filter(generated_at__lt=now - timedelta(hours=2)).delete()

    forecasts = []
    for h in range(1, 73):
        forecast_time = now + timedelta(hours=h)
        if records_data:
            predicted_aqi, predicted_pm25, predicted_pm10 = _predict(records_data, h, forecast_time)
        else:
            # Seasonal mock
            hour_of_day = forecast_time.hour
            base = 60 + 30 * math.exp(-((hour_of_day - 8) ** 2) / 18)
            predicted_aqi = max(10, base + random.gauss(0, 8))
            predicted_pm25 = max(1, predicted_aqi * 0.35 + random.gauss(0, 3))
            predicted_pm10 = max(1, predicted_pm25 * 1.7)

        confidence = max(0.5, 0.95 - h * 0.005)
        f = Forecast(
            forecast_time=forecast_time,
            hours_ahead=h,
            predicted_aqi=round(predicted_aqi, 1),
            predicted_pm25=round(predicted_pm25, 2) if predicted_pm25 else None,
            predicted_pm10=round(predicted_pm10, 2) if predicted_pm10 else None,
            confidence=round(confidence, 3),
        )
        forecasts.append(f)

    Forecast.objects.bulk_create(forecasts)
    logger.info("Generated %d forecast records.", len(forecasts))
    return forecasts


def _predict(records_data, hours_ahead, forecast_time):
    """Simple linear regression with hour-of-day feature."""
    import numpy as np

    aqi_values = [r['aqi'] for r in records_data]
    pm25_values = [r['pm25'] or 0 for r in records_data]
    pm10_values = [r['pm10'] or 0 for r in records_data]
    x = np.arange(len(aqi_values), dtype=float)

    # Linear trend
    if len(x) > 1:
        aqi_coef = np.polyfit(x, aqi_values, 1)
        pm25_coef = np.polyfit(x, pm25_values, 1)
        pm10_coef = np.polyfit(x, pm10_values, 1)
        future_x = len(x) + hours_ahead - 1
        pred_aqi = np.polyval(aqi_coef, future_x)
        pred_pm25 = np.polyval(pm25_coef, future_x)
        pred_pm10 = np.polyval(pm10_coef, future_x)
    else:
        pred_aqi = aqi_values[-1]
        pred_pm25 = pm25_values[-1]
        pred_pm10 = pm10_values[-1]

    # Add hour-of-day seasonality bump
    hour = forecast_time.hour
    seasonal = 15 * math.exp(-((hour - 8) ** 2) / 18) + 12 * math.exp(-((hour - 19) ** 2) / 18)
    pred_aqi = max(5, pred_aqi + seasonal * 0.4)
    pred_pm25 = max(1, pred_pm25)
    pred_pm10 = max(1, pred_pm10)

    return pred_aqi, pred_pm25, pred_pm10
