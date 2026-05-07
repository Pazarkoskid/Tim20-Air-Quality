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

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  AI Model paths
# ─────────────────────────────────────────────

AI_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent.parent / 'backend' / 'python-ai' / 'artifacts' / '24h'
_AI_MODEL    = None
_AI_SCALER   = None
_AI_META     = None
_AI_FEATURES = None


def _load_ai_model():
    global _AI_MODEL, _AI_SCALER, _AI_META, _AI_FEATURES

    if _AI_MODEL is not None:
        return _AI_MODEL, _AI_SCALER, _AI_META, _AI_FEATURES

    try:
        keras_files = [f for f in AI_ARTIFACTS_DIR.glob('*.keras')
                       if '_patched' not in f.name]
        if not keras_files:
            fixed_path = AI_ARTIFACTS_DIR / 'model.keras'
            if not fixed_path.exists():
                logger.warning("No .keras model file found in %s", AI_ARTIFACTS_DIR)
                return None, None, None, None
            keras_files = [fixed_path]

        model_path    = keras_files[0]
        meta_path     = AI_ARTIFACTS_DIR / 'meta.json'
        scaler_path   = AI_ARTIFACTS_DIR / 'scaler.pkl'
        features_path = AI_ARTIFACTS_DIR / 'selected_features.json'

        if not all(p.exists() for p in [meta_path, scaler_path, features_path]):
            logger.warning("Missing artifact files in %s", AI_ARTIFACTS_DIR)
            return None, None, None, None

        with open(meta_path, 'r', encoding='utf-8') as f:
            _AI_META = json.load(f)
        with open(features_path, 'r', encoding='utf-8') as f:
            _AI_FEATURES = json.load(f)['selected_features']
        with open(scaler_path, 'rb') as f:
            _AI_SCALER = pickle.load(f)

        os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
        os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'

        import tensorflow as tf_module
        from tensorflow import keras
        from keras.src.layers.core import lambda_layer as _ll

        # Fix: Keras 3.14 broke Lambda layers saved with 3.13
        _orig_fc = _ll.Lambda.from_config.__func__

        @classmethod
        def _fixed_from_config(cls, config):
            output_shape = config.pop('output_shape', None)
            inst = _orig_fc(cls, config)
            if output_shape:
                inst._fixed_output_shape = output_shape
            return inst

        def _fixed_compute(self, input_shape):
            if hasattr(self, '_fixed_output_shape') and self._fixed_output_shape:
                return self._fixed_output_shape
            if len(input_shape) == 3:
                return (input_shape[0], input_shape[2])
            raise NotImplementedError()

        _orig_call = _ll.Lambda.call
        def _fixed_call(self, inputs, mask=None, training=None):
            if hasattr(self, 'function') and callable(self.function):
                fn = self.function
                if hasattr(fn, '__globals__') and 'tf' not in fn.__globals__:
                    fn.__globals__['tf'] = tf_module
            return _orig_call(self, inputs, mask=mask, training=training)

        _ll.Lambda.from_config         = _fixed_from_config
        _ll.Lambda.compute_output_shape = _fixed_compute
        _ll.Lambda.call                = _fixed_call

        # Patch config.json inside .keras zip to add output_shape
        import zipfile, tempfile as _tmp, shutil as _sh

        _tmpdir = _tmp.mkdtemp()
        try:
            with zipfile.ZipFile(str(model_path)) as _z:
                _z.extractall(_tmpdir)
            _cfg_path = os.path.join(_tmpdir, 'config.json')
            with open(_cfg_path, 'r') as _f:
                _cfg = json.load(_f)

            def _patch_cfg(obj):
                if isinstance(obj, dict):
                    if obj.get('class_name') == 'Lambda':
                        obj['config']['output_shape'] = (None, 96)
                    for v in obj.values():
                        _patch_cfg(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _patch_cfg(v)
            _patch_cfg(_cfg)

            with open(_cfg_path, 'w') as _f:
                json.dump(_cfg, _f)

            _patched_path = str(model_path) + '_patched.keras'
            with zipfile.ZipFile(_patched_path, 'w', zipfile.ZIP_DEFLATED) as _zout:
                for _root, _, _files in os.walk(_tmpdir):
                    for _fn in _files:
                        _fp = os.path.join(_root, _fn)
                        _zout.write(_fp, os.path.relpath(_fp, _tmpdir))
        finally:
            _sh.rmtree(_tmpdir)

        _AI_MODEL = keras.models.load_model(_patched_path, safe_mode=False, compile=False)
        logger.info("Keras AI model loaded successfully from %s", model_path)
        return _AI_MODEL, _AI_SCALER, _AI_META, _AI_FEATURES

    except Exception as exc:
        logger.warning("Could not load AI model: %s", exc)
        return None, None, None, None


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
    return record


# ─────────────────────────────────────────────
#  AI Forecasting
# ─────────────────────────────────────────────

def _run_inference_subprocess(window, scaler, feature_names, patched_path):
    """
    Runs Keras inference in a separate process to avoid Django memory crash
    on Windows with TensorFlow.
    """
    logger.warning("SUBPROCESS starting, patched_path=%s, exists=%s",
                   patched_path, os.path.exists(patched_path))
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


def generate_forecast():
    from airquality.models import AirQualityRecord, Forecast

    cutoff = timezone.now() - timedelta(hours=120)
    records = AirQualityRecord.objects.filter(timestamp__gte=cutoff).order_by('timestamp')
    records_data = list(records.values('timestamp', 'aqi', 'pm25', 'pm10', 'co', 'no2', 'o3', 'so2'))

    now = timezone.now()

    model, scaler, meta, feature_names = _load_ai_model()
    use_keras = model is not None and len(records_data) >= meta.get('lookback', 48)

    ai_pm10_predictions = None
    if use_keras:
        try:
            lookback    = meta['lookback']
            feat_matrix = _build_feature_matrix(records_data, feature_names)
            window       = feat_matrix[-lookback:]
            _patched     = str(AI_ARTIFACTS_DIR / 'model.keras') + '_patched.keras'

            ai_pm10_predictions = _run_inference_subprocess(
                window, scaler, feature_names, _patched
            )
        except Exception as exc:
            logger.warning("Keras inference failed: %s", exc)
            ai_pm10_predictions = None

    forecasts = []
    for h in range(1, 73):
        forecast_time = now + timedelta(hours=h)

        if ai_pm10_predictions is not None and h <= len(ai_pm10_predictions):
            pred_pm10 = max(1.0, float(ai_pm10_predictions[h - 1]))
            pred_pm25 = max(1.0, pred_pm10 / 1.8)
            pred_aqi  = max(5.0, ow_aqi_to_index(None, pred_pm25))
        elif records_data and len(records_data) >= 5:
            pred_aqi, pred_pm25, pred_pm10 = _predict(records_data, h, forecast_time)
        else:
            hour_of_day = forecast_time.hour
            base      = 60 + 30 * math.exp(-((hour_of_day - 8) ** 2) / 18)
            pred_aqi  = max(10, base + random.gauss(0, 8))
            pred_pm25 = max(1, pred_aqi * 0.35)
            pred_pm10 = max(1, pred_pm25 * 1.7)

        confidence = (max(0.75, 0.97 - h * 0.003)
                      if ai_pm10_predictions is not None
                      else max(0.50, 0.95 - h * 0.005))

        forecasts.append(Forecast(
            forecast_time  = forecast_time,
            hours_ahead    = h,
            predicted_aqi  = round(float(pred_aqi), 1),
            predicted_pm25 = round(float(pred_pm25), 2) if pred_pm25 else None,
            predicted_pm10 = round(float(pred_pm10), 2) if pred_pm10 else None,
            confidence     = round(confidence, 3),
        ))

    Forecast.objects.bulk_create(forecasts)

    used_model = ("Keras AI модел"
                  if ai_pm10_predictions is not None
                  else "статистички модел")
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