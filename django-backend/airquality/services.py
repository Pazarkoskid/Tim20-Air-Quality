import os
import random
import math
import logging
import pickle
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  AI Model paths
# ─────────────────────────────────────────────

AI_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / 'backend' / 'python-ai' / 'artifacts'
_AI_MODEL = None
_AI_SCALER = None
_AI_META = None
_AI_FEATURES = None


def _load_ai_model():
    """Lazy-load the Keras model + scaler. Returns (model, scaler, meta, features) or (None,...) on failure."""
    global _AI_MODEL, _AI_SCALER, _AI_META, _AI_FEATURES
    if _AI_MODEL is not None:
        return _AI_MODEL, _AI_SCALER, _AI_META, _AI_FEATURES

    try:
        # Find the keras model file
        keras_files = list(AI_ARTIFACTS_DIR.glob('*.keras'))
        if not keras_files:
            logger.warning("No .keras model file found in %s", AI_ARTIFACTS_DIR)
            return None, None, None, None

        model_path = keras_files[0]
        run_name = model_path.stem  # e.g. pm10_lean_20260327_171406

        meta_path = AI_ARTIFACTS_DIR / f'{run_name}_meta.json'
        scaler_path = AI_ARTIFACTS_DIR / f'{run_name}_scaler.pkl'
        features_path = AI_ARTIFACTS_DIR / f'{run_name}_selected_features.json'

        with open(meta_path, 'r', encoding='utf-8') as f:
            _AI_META = json.load(f)
        with open(features_path, 'r', encoding='utf-8') as f:
            _AI_FEATURES = json.load(f)['selected_features']
        with open(scaler_path, 'rb') as f:
            _AI_SCALER = pickle.load(f)

        # Import keras only when needed
        os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
        from tensorflow import keras  # type: ignore
        _AI_MODEL = keras.models.load_model(str(model_path))
        logger.info("Loaded AI model: %s  features=%d  lookback=%d",
                    run_name, _AI_META['n_features'], _AI_META['lookback'])
        return _AI_MODEL, _AI_SCALER, _AI_META, _AI_FEATURES

    except Exception as exc:
        logger.warning("Could not load AI model: %s — will use statistical forecast.", exc)
        return None, None, None, None


# ─────────────────────────────────────────────
#  AQI helper (OpenWeather uses 1-5 scale)
# ─────────────────────────────────────────────

OW_AQI_MAP = {1: 25, 2: 75, 3: 125, 4: 175, 5: 250}


def ow_aqi_to_index(ow_aqi: int, pm25: float) -> float:
    """Convert OpenWeather AQI (1-5) to a US-style 0-500 AQI using pm2.5."""
    if pm25 is None:
        return float(OW_AQI_MAP.get(ow_aqi, 100))
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
#  Mock / fallback data
# ─────────────────────────────────────────────

def get_mock_data():
    hour = datetime.now().hour
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
    record = AirQualityRecord(**data)
    record.save()
    logger.info("Saved AirQualityRecord id=%s aqi=%.1f source=%s", record.id, record.aqi, record.source)

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
#  AI Forecasting — uses Keras model if available,
#  else falls back to linear regression
# ─────────────────────────────────────────────

def _build_feature_matrix(records_data, feature_names):
    """
    Build feature matrix from records matching the model's expected features.
    records_data: list of dicts with keys: aqi, pm25, pm10, co, no2, o3, so2, timestamp
    Returns numpy array of shape (n_records, n_features).
    """
    import math

    rows = []
    for i, r in enumerate(records_data):
        pm10  = r.get('pm10') or 0
        pm25  = r.get('pm25') or 0  # field is pm25 in dict (mapped from pm2_5)
        aqi   = r.get('aqi') or 0
        co    = r.get('co') or 0
        ts    = r.get('timestamp')
        if ts:
            hour = ts.hour if hasattr(ts, 'hour') else 0
            day  = ts.weekday() if hasattr(ts, 'weekday') else 0
        else:
            hour, day = 0, 0

        hour_sin = math.sin(2 * math.pi * hour / 24)
        hour_cos = math.cos(2 * math.pi * hour / 24)
        day_sin  = math.sin(2 * math.pi * day / 7)
        day_cos  = math.cos(2 * math.pi * day / 7)

        # Diff features — need previous record
        prev = records_data[i - 1] if i > 0 else r
        prev_pm10 = prev.get('pm10') or 0
        prev_pm25 = prev.get('pm25') or 0
        prev_co   = prev.get('co') or 0

        pm10_diff1     = pm10 - prev_pm10
        pm10_absdiff1  = abs(pm10_diff1)
        pm2_5_diff1    = pm25 - prev_pm25
        co_diff1       = co - prev_co

        # 3-step diff (need i-3)
        prev3 = records_data[i - 3] if i >= 3 else records_data[0]
        co_diff3   = co - (prev3.get('co') or 0)
        pm10_diff3 = pm10 - (prev3.get('pm10') or 0)

        # Rolling std of pm10 over last 3
        window = [records_data[max(0, i - j)].get('pm10') or 0 for j in range(3)]
        pm10_roll3_std = float(np.std(window))

        feature_map = {
            'pm10': pm10,
            'pm2_5': pm25,
            'aqi': aqi,
            'hour_sin': hour_sin,
            'hour_cos': hour_cos,
            'day_sin': day_sin,
            'day_cos': day_cos,
            'pm10_diff1': pm10_diff1,
            'pm10_absdiff1': pm10_absdiff1,
            'pm2_5_diff1': pm2_5_diff1,
            'co_diff3': co_diff3,
            'pm10_roll3_std': pm10_roll3_std,
            'co_diff1': co_diff1,
            'pm10_diff3': pm10_diff3,
        }
        rows.append([feature_map.get(f, 0.0) for f in feature_names])

    return np.array(rows, dtype=np.float32)


def generate_forecast():
    from airquality.models import AirQualityRecord, Forecast

    cutoff = timezone.now() - timedelta(hours=72)
    records = AirQualityRecord.objects.filter(timestamp__gte=cutoff).order_by('timestamp')
    records_data = list(records.values('timestamp', 'aqi', 'pm25', 'pm10', 'co', 'no2', 'o3', 'so2'))

    now = timezone.now()
    Forecast.objects.filter(generated_at__lt=now - timedelta(hours=2)).delete()

    # Try Keras model
    model, scaler, meta, feature_names = _load_ai_model()
    use_keras = (
        model is not None
        and len(records_data) >= meta['lookback']
    )

    ai_pm10_predictions = None
    if use_keras:
        try:
            lookback = meta['lookback']
            feat_matrix = _build_feature_matrix(records_data, feature_names)
            # Use last `lookback` rows
            window = feat_matrix[-lookback:]  # (lookback, n_features)
            window_scaled = scaler.transform(window)
            X = window_scaled.reshape(1, lookback, len(feature_names))
            # Model predicts next 24h of pm10
            pred_scaled = model.predict(X, verbose=0)[0]  # shape (horizon,) or (horizon, 1)
            pred_scaled = np.array(pred_scaled).flatten()
            # Inverse transform: rebuild a dummy matrix with pm10 in col 0
            dummy = np.zeros((len(pred_scaled), len(feature_names)), dtype=np.float32)
            dummy[:, 0] = pred_scaled
            ai_pm10_predictions = scaler.inverse_transform(dummy)[:, 0]
            logger.info("Keras model predicted %d steps of PM10", len(ai_pm10_predictions))
        except Exception as exc:
            logger.warning("Keras inference failed: %s — using statistical fallback.", exc)
            ai_pm10_predictions = None

    forecasts = []
    for h in range(1, 73):
        forecast_time = now + timedelta(hours=h)

        if ai_pm10_predictions is not None and h <= len(ai_pm10_predictions):
            # Use Keras-predicted PM10, derive AQI from it
            pred_pm10 = max(1.0, float(ai_pm10_predictions[h - 1]))
            pred_pm25 = max(1.0, pred_pm10 / 1.8)
            pred_aqi  = max(5.0, ow_aqi_to_index(None, pred_pm25))
            # Add small noise for hours beyond 24 (extrapolate)
        elif records_data and len(records_data) >= 5:
            pred_aqi, pred_pm25, pred_pm10 = _predict(records_data, h, forecast_time)
        else:
            hour_of_day = forecast_time.hour
            base = 60 + 30 * math.exp(-((hour_of_day - 8) ** 2) / 18)
            pred_aqi  = max(10, base + random.gauss(0, 8))
            pred_pm25 = max(1, pred_aqi * 0.35 + random.gauss(0, 3))
            pred_pm10 = max(1, pred_pm25 * 1.7)

        confidence = max(0.5, 0.95 - h * 0.005)
        # Keras predictions are more confident in short horizon
        if ai_pm10_predictions is not None and h <= 24:
            confidence = max(0.75, 0.97 - h * 0.003)

        f = Forecast(
            forecast_time=forecast_time,
            hours_ahead=h,
            predicted_aqi=round(float(pred_aqi), 1),
            predicted_pm25=round(float(pred_pm25), 2) if pred_pm25 else None,
            predicted_pm10=round(float(pred_pm10), 2) if pred_pm10 else None,
            confidence=round(confidence, 3),
        )
        forecasts.append(f)

    Forecast.objects.bulk_create(forecasts)
    used_model = "Keras AI модел" if (ai_pm10_predictions is not None) else "статистички модел"
    logger.info("Generated %d forecast records using %s.", len(forecasts), used_model)
    return forecasts, used_model


def _predict(records_data, hours_ahead, forecast_time):
    """Simple linear regression with hour-of-day feature (fallback)."""
    aqi_values  = [r['aqi'] for r in records_data]
    pm25_values = [r['pm25'] or 0 for r in records_data]
    pm10_values = [r['pm10'] or 0 for r in records_data]
    x = np.arange(len(aqi_values), dtype=float)

    if len(x) > 1:
        aqi_coef  = np.polyfit(x, aqi_values, 1)
        pm25_coef = np.polyfit(x, pm25_values, 1)
        pm10_coef = np.polyfit(x, pm10_values, 1)
        future_x  = len(x) + hours_ahead - 1
        pred_aqi  = np.polyval(aqi_coef, future_x)
        pred_pm25 = np.polyval(pm25_coef, future_x)
        pred_pm10 = np.polyval(pm10_coef, future_x)
    else:
        pred_aqi  = aqi_values[-1]
        pred_pm25 = pm25_values[-1]
        pred_pm10 = pm10_values[-1]

    hour = forecast_time.hour
    seasonal = 15 * math.exp(-((hour - 8) ** 2) / 18) + 12 * math.exp(-((hour - 19) ** 2) / 18)
    pred_aqi  = max(5, pred_aqi + seasonal * 0.4)
    pred_pm25 = max(1, pred_pm25)
    pred_pm10 = max(1, pred_pm10)
    return pred_aqi, pred_pm25, pred_pm10
