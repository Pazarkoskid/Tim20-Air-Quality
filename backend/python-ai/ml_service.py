from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import json
import pickle
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, Model, regularizers


@dataclass
class ModelBundle:
    model: tf.keras.Model
    scaler: object
    feature_cols: List[str]
    target_idx: int
    lookback: int
    horizon: int
    name: str


class PM10MLService:
    """
    ML inference service:
      - Loads 24h/48h/72h model bundles once at startup
      - Applies training-aligned feature engineering bridge
      - Routes inference by requested horizon (24/48/72)
    """

    def __init__(self, artifacts_root: Path) -> None:
        self.artifacts_root = artifacts_root
        self.bundles: Dict[str, ModelBundle] = {}
        self._loaded = False

    # ---------------------------
    # Startup / Shutdown
    # ---------------------------
    def load_all(self) -> None:
        self.bundles["24h"] = self._load_bundle("24h")
        self.bundles["48h"] = self._load_bundle("48h")
        self.bundles["72h"] = self._load_bundle("72h")
        self._loaded = True

    def close(self) -> None:
        self.bundles.clear()
        self._loaded = False

    # ---------------------------
    # Public inference
    # ---------------------------
    def forecast(self, history: List[dict], hours: int = 72) -> dict:
        if not self._loaded:
            raise RuntimeError("ML service is not initialized. Call load_all() first.")

        if hours not in (24, 48, 72):
            raise ValueError("hours must be one of: 24, 48, 72")

        # Existing pipeline (unchanged)
        raw_df = self._history_to_df(history)
        engineered = self._feature_engineering_bridge(raw_df)

        predictions: List[float] = []

        if hours == 24:
            run_order = ["24h"]
        elif hours == 48:
            run_order = ["24h", "48h"]
        else:
            run_order = ["24h", "48h", "72h"]

        for key in run_order:
            bundle = self.bundles[key]
            x = self._prepare_tensor_for_bundle(engineered, bundle)  # (1, lookback, n_features)
            y_scaled = bundle.model.predict(x, verbose=0)[0]  # (horizon,)

            y_real = self._inverse_target_only(
                y_scaled=y_scaled,
                scaler=bundle.scaler,
                n_features=len(bundle.feature_cols),
                target_idx=bundle.target_idx,
            )
            predictions.extend(y_real.tolist())

        # ---- NEW: Output post-processing only ----
        # Ensure exact requested length
        hourly_predictions = [float(v) for v in predictions[:hours]]

        # Dynamic 24h chunking
        daily_summary = []
        chunk_size = 24
        for day_idx, start in enumerate(range(0, len(hourly_predictions), chunk_size), start=1):
            chunk = hourly_predictions[start:start + chunk_size]
            if not chunk:
                continue
            daily_summary.append({
                "day": day_idx,
                "max_pm10": float(max(chunk))
            })

        return {
            "requested_hours": hours,
            "daily_summary": daily_summary,
            "hourly_predictions": hourly_predictions
        }

    # ---------------------------
    # Internal loading helpers
    # ---------------------------
    def _load_bundle(self, folder_name: str) -> ModelBundle:
        """
        Load one model bundle from artifacts/<folder_name>/.
        IMPORTANT:
        - Do not load full model graph from .keras due to Lambda deserialization issues.
        - Rebuild architecture in code, then load weights from artifact.
        """
        folder = self.artifacts_root / folder_name
        model_path = folder / "model.keras"
        scaler_path = folder / "scaler.pkl"
        meta_path = folder / "meta.json"
        selected_features_path = folder / "selected_features.json"

        if not model_path.exists():
            raise FileNotFoundError(f"Missing model file: {model_path}")
        if not scaler_path.exists():
            raise FileNotFoundError(f"Missing scaler file: {scaler_path}")
        if not meta_path.exists():
            raise FileNotFoundError(f"Missing meta file: {meta_path}")
        if not selected_features_path.exists():
            raise FileNotFoundError(f"Missing selected_features file: {selected_features_path}")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        with open(selected_features_path, "r", encoding="utf-8") as f:
            sf = json.load(f)

        feature_cols = sf.get("selected_features") or meta.get("feature_cols")
        if not feature_cols:
            raise ValueError(f"No feature columns found in {selected_features_path} / {meta_path}")

        target_idx = int(meta.get("target_idx", 0))
        lookback = int(meta.get("lookback", 48))
        horizon = int(meta.get("horizon_trained", 24))
        n_features = len(feature_cols)

        # Build Lambda-free architecture
        model = self._build_lean_model(
            lookback=lookback,
            n_features=n_features,
            horizon=horizon
        )

        # Load only weights from .keras
        try:
            model.load_weights(str(model_path))
        except Exception as e:
            raise RuntimeError(
                f"Failed to load weights from '{model_path}' for bundle '{folder_name}'. "
                "This usually means artifact architecture mismatch. "
                "Please re-export models with the same Lambda-free architecture used by backend."
            ) from e

        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)

        return ModelBundle(
            model=model,
            scaler=scaler,
            feature_cols=feature_cols,
            target_idx=target_idx,
            lookback=lookback,
            horizon=horizon,
            name=folder_name,
        )

    def _build_lean_model(self, lookback: int, n_features: int, horizon: int) -> Model:
        """
        Lambda-free inference architecture matching training intent:
          Input -> Conv1D -> Dropout -> BiLSTM(seq) -> attention weights -> Multiply
          -> GlobalAveragePooling1D -> Dense -> Dropout -> Dense(horizon)
        """
        inp = layers.Input(shape=(lookback, n_features))

        x = layers.Conv1D(
            filters=48,
            kernel_size=3,
            padding="causal",
            activation="relu",
            kernel_regularizer=regularizers.l2(1e-4),
            name="conv1d",
        )(inp)
        x = layers.Dropout(0.20, name="dropout_conv")(x)

        x = layers.Bidirectional(
            layers.LSTM(
                48,
                return_sequences=True,
                dropout=0.15,
                recurrent_dropout=0.0,
                name="lstm_core",
            ),
            name="bilstm",
        )(x)

        score = layers.Dense(1, activation="tanh", name="attn_score")(x)
        score = layers.Softmax(axis=1, name="attn_softmax")(score)
        weighted = layers.Multiply(name="attn_weighted")([x, score])

        # Replaces old Lambda(reduce_sum) with stable builtin layer
        ctx = layers.GlobalAveragePooling1D(name="attn_pool")(weighted)

        x = layers.Dense(
            96,
            activation="relu",
            kernel_regularizer=regularizers.l2(1e-4),
            name="dense_96",
        )(ctx)
        x = layers.Dropout(0.25, name="dropout_dense")(x)
        out = layers.Dense(horizon, name="forecast_head")(x)

        return Model(inp, out, name="pm10_lean_inference")

    # ---------------------------
    # Internal preprocessing
    # ---------------------------
    @staticmethod
    def _history_to_df(history: List[dict]) -> pd.DataFrame:
        df = pd.DataFrame(history).copy()
        required = {"timestamp", "pm10", "pm2_5", "co", "aqi"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing required raw fields: {missing}")

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").set_index("timestamp")
        return df

    @staticmethod
    def _feature_engineering_bridge(raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        Mirror training-style feature engineering:
          - cyclical time
          - diffs
          - rolling means/stds
          - pm10 momentum/absdiff
          - drop NaNs
        """
        d = raw_df.copy()

        # cyclical time
        hours = d.index.hour
        d["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
        d["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)

        days = d.index.dayofweek
        d["day_sin"] = np.sin(2 * np.pi * days / 7.0)
        d["day_cos"] = np.cos(2 * np.pi * days / 7.0)

        # dynamic features
        base_cols = ["pm10", "pm2_5", "aqi", "co", "no2"]
        for col in base_cols:
            if col not in d.columns:
                continue

            d[f"{col}_diff1"] = d[col].diff(1)
            d[f"{col}_diff3"] = d[col].diff(3)
            d[f"{col}_diff6"] = d[col].diff(6)

            for w in [3, 6, 12, 24]:
                d[f"{col}_roll{w}_mean"] = d[col].rolling(w).mean()
                d[f"{col}_roll{w}_std"] = d[col].rolling(w).std()

        eps = 1e-6
        d["pm10_mom24"] = d["pm10"] / (d["pm10_roll24_mean"] + eps)
        d["pm10_absdiff1"] = np.abs(d["pm10_diff1"])
        d["pm10_absdiff3"] = np.abs(d["pm10_diff3"])

        d = d.dropna()
        return d

    def _prepare_tensor_for_bundle(self, engineered_df: pd.DataFrame, bundle: ModelBundle) -> np.ndarray:
        missing_features = [c for c in bundle.feature_cols if c not in engineered_df.columns]
        if missing_features:
            raise ValueError(
                f"Missing engineered features for bundle '{bundle.name}': {missing_features}"
            )

        if len(engineered_df) < bundle.lookback:
            raise ValueError(
                f"Not enough rows after feature engineering for bundle '{bundle.name}'. "
                f"Need >= {bundle.lookback}, got {len(engineered_df)}. "
                "Provide more history buffer in request."
            )

        window = engineered_df[bundle.feature_cols].tail(bundle.lookback).copy()
        scaled = bundle.scaler.transform(window.values)
        x = scaled.reshape(1, bundle.lookback, len(bundle.feature_cols))
        return x

    @staticmethod
    def _inverse_target_only(
        y_scaled: np.ndarray,
        scaler: object,
        n_features: int,
        target_idx: int,
    ) -> np.ndarray:
        dummy = np.zeros((len(y_scaled), n_features), dtype=float)
        dummy[:, target_idx] = y_scaled
        inv = scaler.inverse_transform(dummy)[:, target_idx]
        return inv