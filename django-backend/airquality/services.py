
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
import tensorflow as tf
from tensorflow.keras import layers, Model, regularizers

tf.keras.config.enable_unsafe_deserialization()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  AI Model paths (multi-horizon)
# ─────────────────────────────────────────────

AI_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "backend" / "python-ai" / "artifacts"
HORIZON_DIRS = {
    24: AI_BASE_DIR / "24h",
    48: AI_BASE_DIR / "48h",
    72: AI_BASE_DIR / "72h",
}

_AI_BUNDLES = {}  # {horizon: (model, scaler, meta, features)}

# ─────────────────────────────────────────────
#  Custom Keras objects
# ─────────────────────────────────────────────

@tf.keras.utils.register_keras_serializable(package="pm10")
def reduce_sum_time_axis(t):
    return tf.reduce_sum(t, axis=1)


def build_lean_model(lookback, n_features, horizon):
    inp = layers.Input(shape=(lookback, n_features))

    x = layers.Conv1D(filters=48, kernel_size=3, padding='causal', activation='relu',
                      kernel_regularizer=regularizers.l2(1e-4))(inp)
    x = layers.Dropout(0.20)(x)
    x = layers.Bidirectional(layers.LSTM(48, return_sequences=True, dropout=0.15, recurrent_dropout=0.0))(x)

    score = layers.Dense(1, activation='tanh')(x)
    score = layers.Softmax(axis=1)(score)
    weighted = layers.Multiply()([x, score])

    ctx = layers.Lambda(reduce_sum_time_axis, output_shape=lambda s: (s[0], s[2]))(weighted)

    x = layers.Dense(96, activation='relu', kernel_regularizer=regularizers.l2(1e-4))(ctx)
    x = layers.Dropout(0.25)(x)
    # Секој модел исплукува точно 24 часа
    out = layers.Dense(horizon)(x)

    return Model(inp, out)


@tf.keras.utils.register_keras_serializable(package="pm10")
class PeakRampLoss(tf.keras.losses.Loss):
    def __init__(self, q75, peak_w=1.8, ramp_w=0.8, name="peak_ramp_loss",
                 reduction=tf.keras.losses.Reduction.SUM_OVER_BATCH_SIZE, **kwargs):
        super().__init__(name=name, reduction=reduction, **kwargs)
        self.q75 = tf.constant(q75, dtype=tf.float32)
        self.peak_w = peak_w
        self.ramp_w = ramp_w

    def call(self, y_true, y_pred):
        abs_err = tf.abs(y_true - y_pred)
        peak_mask = tf.cast(y_true >= self.q75, tf.float32)
        w_peak = 1.0 + peak_mask * (self.peak_w - 1.0)
        dy_true = tf.abs(y_true[:, 1:] - y_true[:, :-1])
        dy_true = tf.concat([dy_true[:, :1], dy_true], axis=1)
        w_ramp = 1.0 + self.ramp_w * tf.tanh(dy_true)
        w = w_peak * w_ramp
        return tf.reduce_mean(w * abs_err)

    def get_config(self):
        config = super().get_config()
        config.update({
            "q75": float(self.q75.numpy()) if hasattr(self.q75, "numpy") else float(self.q75),
            "peak_w": self.peak_w,
            "ramp_w": self.ramp_w,
        })
        return config

    @classmethod
    def from_config(cls, config):
        return cls(**config)


CUSTOM_OBJECTS = {
    "reduce_sum_time_axis": reduce_sum_time_axis,
    "PeakRampLoss": PeakRampLoss,
}

# ─────────────────────────────────────────────
#  Loader
# ─────────────────────────────────────────────
def _load_ai_bundle(horizon: int):
    """Load model bundle for a specific horizon. Returns dict or None."""
    if horizon in _AI_BUNDLES:
        return _AI_BUNDLES[horizon]

    bundle_dir = HORIZON_DIRS.get(horizon)
    if not bundle_dir or not bundle_dir.exists():
        logger.warning("AI bundle missing for horizon=%s (%s)", horizon, bundle_dir)
        _AI_BUNDLES[horizon] = None
        return None

    try:
        keras_files = list(bundle_dir.glob("*.keras"))
        if not keras_files:
            logger.warning("No .keras model found in %s", bundle_dir)
            _AI_BUNDLES[horizon] = None
            return None

        model_path = keras_files[0]
        meta_path = bundle_dir / "meta.json"
        scaler_path = bundle_dir / "scaler.pkl"
        features_path = bundle_dir / "selected_features.json"

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        with open(features_path, "r", encoding="utf-8") as f:
            feature_names = json.load(f)["selected_features"]
        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)

        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        from tensorflow import keras

        # --- НОВ БЕЗБЕДЕН НАЧИН НА ВЧИТУВАЊЕ ---
        # 1. Ја креираме празната архитектура (читаме колку features има од meta.json)
        model = build_lean_model(
            lookback=meta["lookback"],
            n_features=meta["n_features"],
            horizon=24
        )

        # 2. Ги вчитуваме само тежините за да го избегнеме C++ багот на Windows
        model.load_weights(str(model_path))
        # --------------------------------------

        logger.info(
            "Loaded AI bundle horizon=%s model=%s features=%d lookback=%s",
            horizon, model_path.name, meta["n_features"], meta["lookback"]
        )

        bundle = {
            "model": model,
            "scaler": scaler,
            "meta": meta,
            "features": feature_names,
        }
        _AI_BUNDLES[horizon] = bundle
        return bundle

    except Exception as exc:
        logger.warning("Failed to load AI bundle horizon=%s: %s", horizon, exc)
        _AI_BUNDLES[horizon] = None
        return None

# ─────────────────────────────────────────────
#  AQI helper (OpenWeather uses 1-5 scale)
# ─────────────────────────────────────────────

OW_AQI_MAP = {1: 25, 2: 75, 3: 125, 4: 175, 5: 250}


def ow_aqi_to_index(ow_aqi: int, pm25: float) -> float:
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
#  Feature matrix builder
# ─────────────────────────────────────────────

def _build_feature_matrix(records_data, feature_names):
    import math

    def get_val(idx, key, default=0.0):
        val = records_data[idx].get(key)
        return float(val) if val is not None else float(default)

    rows = []
    for i, r in enumerate(records_data):
        pm10 = get_val(i, "pm10")
        pm25 = get_val(i, "pm25")
        aqi = get_val(i, "aqi")
        co = get_val(i, "co")
        no2 = get_val(i, "no2")

        ts = r.get("timestamp")
        if ts:
            hour = ts.hour if hasattr(ts, "hour") else 0
            day = ts.weekday() if hasattr(ts, "weekday") else 0
        else:
            hour, day = 0, 0

        hour_sin = math.sin(2 * math.pi * hour / 24)
        hour_cos = math.cos(2 * math.pi * hour / 24)
        day_sin = math.sin(2 * math.pi * day / 7)
        day_cos = math.cos(2 * math.pi * day / 7)

        prev = records_data[i - 1] if i > 0 else r
        prev3 = records_data[i - 3] if i >= 3 else records_data[0]
        prev6 = records_data[i - 6] if i >= 6 else records_data[0]

        prev_pm10 = float(prev.get("pm10") or 0)
        prev_pm25 = float(prev.get("pm25") or 0)
        prev_aqi = float(prev.get("aqi") or 0)
        prev_co = float(prev.get("co") or 0)
        prev_no2 = float(prev.get("no2") or 0)

        prev3_pm10 = float(prev3.get("pm10") or 0)
        prev3_pm25 = float(prev3.get("pm25") or 0)
        prev3_aqi = float(prev3.get("aqi") or 0)
        prev3_co = float(prev3.get("co") or 0)
        prev3_no2 = float(prev3.get("no2") or 0)

        prev6_pm10 = float(prev6.get("pm10") or 0)
        prev6_pm25 = float(prev6.get("pm25") or 0)
        prev6_aqi = float(prev6.get("aqi") or 0)
        prev6_co = float(prev6.get("co") or 0)
        prev6_no2 = float(prev6.get("no2") or 0)

        pm10_diff1 = pm10 - prev_pm10
        pm10_diff3 = pm10 - prev3_pm10
        pm10_diff6 = pm10 - prev6_pm10
        pm10_absdiff1 = abs(pm10_diff1)
        pm10_absdiff3 = abs(pm10_diff3)

        pm2_5_diff1 = pm25 - prev_pm25
        pm2_5_diff3 = pm25 - prev3_pm25
        pm2_5_diff6 = pm25 - prev6_pm25

        aqi_diff1 = aqi - prev_aqi
        aqi_diff3 = aqi - prev3_aqi
        aqi_diff6 = aqi - prev6_aqi

        co_diff1 = co - prev_co
        co_diff3 = co - prev3_co
        co_diff6 = co - prev6_co

        no2_diff1 = no2 - prev_no2
        no2_diff3 = no2 - prev3_no2
        no2_diff6 = no2 - prev6_no2

        def roll_window(key, w):
            return [float(records_data[max(0, i - j)].get(key) or 0) for j in range(w)]

        def roll_mean(key, w):
            return float(np.mean(roll_window(key, w)))

        def roll_std(key, w):
            return float(np.std(roll_window(key, w)))

        eps = 1e-6
        pm10_roll24_mean = roll_mean("pm10", 24)
        pm10_mom24 = pm10 / (pm10_roll24_mean + eps)

        feature_map = {
            "pm10": pm10,
            "pm2_5": pm25,
            "aqi": aqi,
            "co": co,
            "no2": no2,
            "hour_sin": hour_sin,
            "hour_cos": hour_cos,
            "day_sin": day_sin,
            "day_cos": day_cos,
            "pm10_diff1": pm10_diff1,
            "pm10_diff3": pm10_diff3,
            "pm10_diff6": pm10_diff6,
            "pm10_absdiff1": pm10_absdiff1,
            "pm10_absdiff3": pm10_absdiff3,
            "pm2_5_diff1": pm2_5_diff1,
            "pm2_5_diff3": pm2_5_diff3,
            "pm2_5_diff6": pm2_5_diff6,
            "aqi_diff1": aqi_diff1,
            "aqi_diff3": aqi_diff3,
            "aqi_diff6": aqi_diff6,
            "co_diff1": co_diff1,
            "co_diff3": co_diff3,
            "co_diff6": co_diff6,
            "no2_diff1": no2_diff1,
            "no2_diff3": no2_diff3,
            "no2_diff6": no2_diff6,
            "pm10_roll3_mean": roll_mean("pm10", 3),
            "pm10_roll3_std": roll_std("pm10", 3),
            "pm10_roll6_mean": roll_mean("pm10", 6),
            "pm10_roll6_std": roll_std("pm10", 6),
            "pm10_roll12_mean": roll_mean("pm10", 12),
            "pm10_roll12_std": roll_std("pm10", 12),
            "pm10_roll24_mean": pm10_roll24_mean,
            "pm10_roll24_std": roll_std("pm10", 24),
            "pm2_5_roll3_mean": roll_mean("pm25", 3),
            "pm2_5_roll3_std": roll_std("pm25", 3),
            "pm2_5_roll6_mean": roll_mean("pm25", 6),
            "pm2_5_roll6_std": roll_std("pm25", 6),
            "pm2_5_roll12_mean": roll_mean("pm25", 12),
            "pm2_5_roll12_std": roll_std("pm25", 12),
            "pm2_5_roll24_mean": roll_mean("pm25", 24),
            "pm2_5_roll24_std": roll_std("pm25", 24),
            "aqi_roll3_mean": roll_mean("aqi", 3),
            "aqi_roll3_std": roll_std("aqi", 3),
            "aqi_roll6_mean": roll_mean("aqi", 6),
            "aqi_roll6_std": roll_std("aqi", 6),
            "aqi_roll12_mean": roll_mean("aqi", 12),
            "aqi_roll12_std": roll_std("aqi", 12),
            "aqi_roll24_mean": roll_mean("aqi", 24),
            "aqi_roll24_std": roll_std("aqi", 24),
            "co_roll3_mean": roll_mean("co", 3),
            "co_roll3_std": roll_std("co", 3),
            "co_roll6_mean": roll_mean("co", 6),
            "co_roll6_std": roll_std("co", 6),
            "co_roll12_mean": roll_mean("co", 12),
            "co_roll12_std": roll_std("co", 12),
            "co_roll24_mean": roll_mean("co", 24),
            "co_roll24_std": roll_std("co", 24),
            "no2_roll3_mean": roll_mean("no2", 3),
            "no2_roll3_std": roll_std("no2", 3),
            "no2_roll6_mean": roll_mean("no2", 6),
            "no2_roll6_std": roll_std("no2", 6),
            "no2_roll12_mean": roll_mean("no2", 12),
            "no2_roll12_std": roll_std("no2", 12),
            "no2_roll24_mean": roll_mean("no2", 24),
            "no2_roll24_std": roll_std("no2", 24),
            "pm10_mom24": pm10_mom24,
        }

        rows.append([feature_map.get(f, 0.0) for f in feature_names])

    return np.array(rows, dtype=np.float32)


# ─────────────────────────────────────────────
#  Forecast generation
# ─────────────────────────────────────────────
#
def generate_forecast():
    from airquality.models import AirQualityRecord, Forecast

    cutoff = timezone.now() - timedelta(hours=72)
    records = AirQualityRecord.objects.filter(timestamp__gte=cutoff).order_by("timestamp")
    records_data = list(records.values("timestamp", "aqi", "pm25", "pm10", "co", "no2", "o3", "so2"))

    now = timezone.now()
    Forecast.objects.filter(generated_at__lt=now - timedelta(hours=2)).delete()

    bundles = {
        24: _load_ai_bundle(24),
        48: _load_ai_bundle(48),
        72: _load_ai_bundle(72),
    }

    preds = {24: None, 48: None, 72: None}

    for horizon, bundle in bundles.items():
        if not bundle:
            logger.warning("Model bundle %dh not loaded — fallback will be used.", horizon)
            continue

        model = bundle["model"]
        scaler = bundle["scaler"]
        meta = bundle["meta"]
        feature_names = bundle["features"]

        if len(records_data) < meta["lookback"]:
            logger.warning("Not enough records for %dh (need %d).", horizon, meta["lookback"])
            continue

        try:
            lookback = meta["lookback"]
            feat_matrix = _build_feature_matrix(records_data, feature_names)
            window = feat_matrix[-lookback:]
            window_scaled = scaler.transform(window)
            X = window_scaled.reshape(1, lookback, len(feature_names))
            pred_scaled = np.array(model.predict(X, verbose=0)[0]).flatten()

            dummy = np.zeros((len(pred_scaled), len(feature_names)), dtype=np.float32)
            target_idx = meta.get("target_idx", 0)
            dummy[:, target_idx] = pred_scaled
            preds[horizon] = scaler.inverse_transform(dummy)[:, target_idx]

            logger.info("Predictions ready for %dh horizon (%d steps).", horizon, len(preds[horizon]))
        except Exception as exc:
            logger.warning("Keras inference failed for %dh: %s", horizon, exc)
            preds[horizon] = None

    forecasts = []
    for h in range(1, 73):
        forecast_time = now + timedelta(hours=h)

        pred_pm10 = None
        if h <= 24 and preds[24] is not None:
            pred_pm10 = preds[24][h - 1]
        elif 25 <= h <= 48 and preds[48] is not None:
            pred_pm10 = preds[48][h - 25]
        elif 49 <= h <= 72 and preds[72] is not None:
            pred_pm10 = preds[72][h - 49]

        if pred_pm10 is not None:
            pred_pm10 = float(pred_pm10)


            if pred_pm10 > 300:
                avg_safe = ((preds[24][-1] if preds[24] is not None else 50) +
                            (preds[72][0] if preds[72] is not None else 50)) / 2
                pred_pm10 = avg_safe
            pred_pm10 = max(1.0, pred_pm10)
            pred_pm25 = max(1.0, pred_pm10 / 1.8)
            pred_aqi = max(5.0, ow_aqi_to_index(None, pred_pm25))
        elif records_data and len(records_data) >= 5:
            pred_aqi, pred_pm25, pred_pm10 = _predict(records_data, h, forecast_time)
            logger.info("Hour %d uses statistical model", h)
        else:
            hour_of_day = forecast_time.hour
            base = 60 + 30 * math.exp(-((hour_of_day - 8) ** 2) / 18)
            pred_aqi = max(10, base + random.gauss(0, 8))
            pred_pm25 = max(1, pred_aqi * 0.35 + random.gauss(0, 3))
            pred_pm10 = max(1, pred_pm25 * 1.7)

        confidence = max(0.5, 0.95 - h * 0.005)
        if pred_pm10 is not None and h <= 24:
            confidence = max(0.75, 0.97 - h * 0.003)

        confidence = confidence * 100
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
    used_model = "Deep Learning (BiLSTM)"
    logger.info("Generated %d forecast records using %s.", len(forecasts), used_model)
    return forecasts, used_model





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



def analyze_trends(days=30):
    from airquality.models import AirQualityRecord
    cutoff = timezone.now() - timedelta(days=days)
    records = AirQualityRecord.objects.filter(timestamp__gte=cutoff).order_by('timestamp')

    if records.count() < 7:
        return None

    aqi_values = [r.aqi for r in records]

    # Trend calculation (linear regression)
    x = np.arange(len(aqi_values), dtype=float)
    if len(x) > 1:
        coeffs = np.polyfit(x, aqi_values, 1)
        slope = coeffs[0]
        avg_aqi = np.mean(aqi_values)

        if slope > 0.1:
            trend = "📈 Се влошува"
        elif slope < -0.1:
            trend = "📉 Се подобрува"
        else:
            trend = "➡️ Стабилно"

        return {
            'trend': trend,
            'slope': round(slope, 4),
            'avg_aqi': round(avg_aqi, 1),
            'period_days': days
        }
    return None
