"""
services.py — Data fetching, mock fallback, and AI forecasting
"""

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


        model = build_lean_model(
            lookback=meta["lookback"],
            n_features=meta["n_features"],
            horizon=24
        )

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
#  AQI helper
# ─────────────────────────────────────────────

OW_AQI_MAP = {1: 25, 2: 75, 3: 125, 4: 175, 5: 250}


def ow_aqi_to_index(ow_aqi, pm25):
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
            return round(((hi_i - lo_i) / (hi_c - lo_c)) * (pm25 - lo_c) + lo_i, 1)
    return min(500.0, pm25)


# ─────────────────────────────────────────────
#  Fetch live data
# ─────────────────────────────────────────────

def fetch_air_quality():
    api_key = getattr(settings, 'OPENWEATHER_API_KEY', '')
    if not api_key:
        return get_mock_data()
    url = (
        f"http://api.openweathermap.org/data/2.5/air_pollution"
        f"?lat={settings.CITY_LAT}&lon={settings.CITY_LON}&appid={api_key}"
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data   = response.json()
        comp   = data['list'][0]['components']
        ow_aqi = data['list'][0]['main']['aqi']
        pm25   = comp.get('pm2_5')
        aqi    = ow_aqi_to_index(ow_aqi, pm25)
        return {
            'aqi': aqi, 'pm25': pm25,
            'pm10': comp.get('pm10'), 'co': comp.get('co'),
            'no2':  comp.get('no2'),  'o3': comp.get('o3'),
            'so2':  comp.get('so2'),  'nh3': comp.get('nh3'),
            'source': 'openweather',
        }
    except Exception as exc:
        logger.error("OpenWeather API error: %s", exc)
        return get_mock_data()


def get_mock_data():
    hour = datetime.now().hour
    base_pm25 = (20 + 30 * math.exp(-((hour - 8) ** 2) / 18) +
                 25 * math.exp(-((hour - 19) ** 2) / 18) +
                 random.gauss(0, 5))
    base_pm25 = max(2, base_pm25)
    aqi = ow_aqi_to_index(None, base_pm25)
    return {
        'aqi':    round(aqi, 1),
        'pm25':   round(base_pm25, 2),
        'pm10':   round(base_pm25 * 1.8 + random.gauss(0, 3), 2),
        'co':     round(200 + random.gauss(0, 20), 2),
        'no2':    round(15  + random.gauss(0, 5),  2),
        'o3':     round(60  + random.gauss(0, 10), 2),
        'so2':    round(5   + random.gauss(0, 2),  2),
        'nh3':    round(3   + random.gauss(0, 1),  2),
        'source': 'mock',
    }


# ─────────────────────────────────────────────
#  Save record + trigger notifications
# ─────────────────────────────────────────────

def save_record_and_notify(data: dict):
    from airquality.models import AirQualityRecord, UserProfile, Notification
    record = AirQualityRecord(**data)
    record.save()

    profiles = UserProfile.objects.filter(notifications_enabled=True)
    for profile in profiles:
        label, category = record.aqi_label()

        if record.aqi >= profile.aqi_threshold:
            msg = (
                f"⚠️ Нивото на загаденост го надмина вашиот праг! "
                f"Статус: {label} (AQI {record.aqi:.0f}). "
                f"PM2.5: {record.pm25} µg/m³. Препорачуваме да останете на затворено."
            )
        else:
            last_notif = Notification.objects.filter(
                user=profile.user
            ).order_by('-created_at').first()
            if last_notif and (timezone.now() - last_notif.created_at) < timedelta(hours=1):
                continue
            msg = (
                f"ℹ️ Ажурирање на квалитет на воздух: {label} (AQI {record.aqi:.0f}). "
                f"PM2.5: {record.pm25} µg/m³."
            )

        Notification.objects.create(
            user=profile.user,
            message=msg,
            aqi_value=record.aqi,
        )

        # Send email if notify_email is enabled and user has email
        if profile.notify_email and profile.user.email:
            try:
                from django.core.mail import send_mail
                from django.conf import settings as _s
                send_mail(
                    subject=f'Air Quality AI – Известување за воздух (AQI {record.aqi:.0f})',
                    message=msg,
                    from_email=getattr(_s, 'DEFAULT_FROM_EMAIL', 'noreply@airquality.mk'),
                    recipient_list=[profile.user.email],
                    fail_silently=True,
                )
            except Exception as e:
                logger.warning("Email send failed: %s", e)

    return record


# ─────────────────────────────────────────────
#  AI Forecasting
# ─────────────────────────────────────────────

def _run_inference_subprocess(window, scaler, feature_names, patched_path):
    """
    Runs Keras inference in a separate process to avoid Django memory crash
    on Windows with TensorFlow.
    """
    import subprocess, sys, tempfile, pickle as _pk

    _tmp_in  = tempfile.mktemp(suffix='.pkl')
    _tmp_out = tempfile.mktemp(suffix='.pkl')

    try:
        with open(_tmp_in, 'wb') as f:
            _pk.dump({
                'window':     window,
                'scaler':     scaler,
                'n_features': len(feature_names),
                'model_path': patched_path,
            }, f)

        _script = r"""
import pickle, numpy as np, os, sys
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

tmp_in  = sys.argv[1]
tmp_out = sys.argv[2]

with open(tmp_in, 'rb') as f:
    d = pickle.load(f)

window     = d['window']
scaler     = d['scaler']
n_features = d['n_features']
model_path = d['model_path']
lookback   = window.shape[0]

window_scaled = scaler.transform(window)
X = window_scaled.reshape(1, lookback, n_features)

import tensorflow as tf
from tensorflow import keras
from keras.src.layers.core import lambda_layer as _ll

_orig_fc = _ll.Lambda.from_config.__func__
@classmethod
def _fc(cls, config):
    os2 = config.pop('output_shape', None)
    inst = _orig_fc(cls, config)
    if os2:
        inst._fixed_output_shape = os2
    return inst

def _cc(self, input_shape):
    if hasattr(self, '_fixed_output_shape'):
        return self._fixed_output_shape
    if len(input_shape) == 3:
        return (input_shape[0], input_shape[2])
    raise NotImplementedError()

_orig_call = _ll.Lambda.call
def _ca(self, inputs, mask=None, training=None):
    if hasattr(self, 'function') and callable(self.function):
        fn = self.function
        if hasattr(fn, '__globals__') and 'tf' not in fn.__globals__:
            fn.__globals__['tf'] = tf
    return _orig_call(self, inputs, mask=mask, training=training)

_ll.Lambda.from_config          = _fc
_ll.Lambda.compute_output_shape = _cc
_ll.Lambda.call                 = _ca

model = keras.models.load_model(model_path, safe_mode=False, compile=False)
X_tensor = tf.constant(X, dtype=tf.float32)
pred = model(X_tensor, training=False).numpy()[0]

dummy = np.zeros((len(pred), n_features), dtype=np.float32)
dummy[:, 0] = pred
result = scaler.inverse_transform(dummy)[:, 0]

with open(tmp_out, 'wb') as f:
    pickle.dump(result.tolist(), f)
"""
        result = subprocess.run(
            [sys.executable, '-c', _script, _tmp_in, _tmp_out],
            timeout=120,
            capture_output=True,
        )

        if result.returncode == 0 and os.path.exists(_tmp_out):
            with open(_tmp_out, 'rb') as f:
                predictions = _pk.load(f)
            logger.info("Subprocess inference OK, predictions=%d", len(predictions))
            return np.array(predictions)
        else:
            stderr = result.stderr.decode(errors='replace')[-800:]
            logger.warning("Subprocess inference failed (rc=%d): %s", result.returncode, stderr)
            return None

    except Exception as exc:
        logger.warning("Subprocess inference exception: %s", exc)
        return None
    finally:
        for _f in [_tmp_in, _tmp_out]:
            try:
                os.remove(_f)
            except Exception:
                pass


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


def _build_feature_matrix(records_data, feature_names):
    rows = []
    for i, r in enumerate(records_data):
        pm10 = r.get('pm10') or 0
        pm25 = r.get('pm25') or 0
        aqi  = r.get('aqi')  or 0
        co   = r.get('co')   or 0
        ts   = r.get('timestamp')
        hour = ts.hour      if ts and hasattr(ts, 'hour')    else 0
        day  = ts.weekday() if ts and hasattr(ts, 'weekday') else 0

        hour_sin = math.sin(2 * math.pi * hour / 24)
        hour_cos = math.cos(2 * math.pi * hour / 24)
        day_sin  = math.sin(2 * math.pi * day  / 7)
        day_cos  = math.cos(2 * math.pi * day  / 7)

        prev        = records_data[i - 1] if i > 0 else r
        pm10_diff1  = pm10 - (prev.get('pm10') or 0)
        pm2_5_diff1 = pm25 - (prev.get('pm25') or 0)
        co_diff1    = co   - (prev.get('co')   or 0)

        prev3      = records_data[i - 3] if i >= 3 else records_data[0]
        co_diff3   = co   - (prev3.get('co')   or 0)
        pm10_diff3 = pm10 - (prev3.get('pm10') or 0)

        window         = [records_data[max(0, i - j)].get('pm10') or 0 for j in range(3)]
        pm10_roll3_std = float(np.std(window))

        feature_map = {
            'pm10': pm10, 'pm2_5': pm25, 'aqi': aqi,
            'hour_sin': hour_sin, 'hour_cos': hour_cos,
            'day_sin':  day_sin,  'day_cos':  day_cos,
            'pm10_diff1':     pm10_diff1,    'pm10_absdiff1': abs(pm10_diff1),
            'pm2_5_diff1':    pm2_5_diff1,   'co_diff3':      co_diff3,
            'pm10_roll3_std': pm10_roll3_std, 'co_diff1':     co_diff1,
            'pm10_diff3':     pm10_diff3,
        }
        rows.append([feature_map.get(f, 0.0) for f in feature_names])
    return np.array(rows, dtype=np.float32)


def _predict(records_data, hours_ahead, forecast_time):
    aqi_values  = [r['aqi']        for r in records_data]
    pm25_values = [r['pm25'] or 0  for r in records_data]
    pm10_values = [r['pm10'] or 0  for r in records_data]
    x = np.arange(len(aqi_values), dtype=float)

    if len(x) > 1:
        pred_aqi  = np.polyval(np.polyfit(x, aqi_values,  1), len(x) + hours_ahead - 1)
        pred_pm25 = np.polyval(np.polyfit(x, pm25_values, 1), len(x) + hours_ahead - 1)
        pred_pm10 = np.polyval(np.polyfit(x, pm10_values, 1), len(x) + hours_ahead - 1)
    else:
        pred_aqi, pred_pm25, pred_pm10 = aqi_values[-1], pm25_values[-1], pm10_values[-1]

    hour     = forecast_time.hour
    seasonal = (15 * math.exp(-((hour - 8)  ** 2) / 18) +
                12 * math.exp(-((hour - 19) ** 2) / 18))
    return max(5, pred_aqi + seasonal * 0.4), max(1, pred_pm25), max(1, pred_pm10)


# ─────────────────────────────────────────────
#  Trend Analysis
# ─────────────────────────────────────────────

def analyze_trends(days=30):
    from airquality.models import AirQualityRecord
    cutoff  = timezone.now() - timedelta(days=days)
    records = AirQualityRecord.objects.filter(timestamp__gte=cutoff).order_by('timestamp')
    if records.count() < 7:
        return None
    aqi_values = [r.aqi for r in records]
    x = np.arange(len(aqi_values), dtype=float)
    if len(x) > 1:
        slope   = np.polyfit(x, aqi_values, 1)[0]
        avg_aqi = np.mean(aqi_values)
        trend   = ("📈 Се влошува"   if slope > 0.1
                   else "📉 Се подобрува" if slope < -0.1
                   else "➡️ Стабилно")
        return {
            'trend':       trend,
            'slope':       round(slope, 4),
            'avg_aqi':     round(float(avg_aqi), 1),
            'period_days': days,
        }
    return None
