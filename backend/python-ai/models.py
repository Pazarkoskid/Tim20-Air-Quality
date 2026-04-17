from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SensorPoint(BaseModel):
    """
    One raw sensor observation.
    """
    timestamp: datetime = Field(..., description="Timestamp of the observation (ISO format).")
    pm10: float = Field(..., description="PM10 concentration.")
    pm2_5: float = Field(..., description="PM2.5 concentration.")
    co: float = Field(..., description="CO concentration.")
    aqi: float = Field(..., description="Air Quality Index value.")
    no2: Optional[float] = Field(None, description="Optional NO2 concentration.")


class ForecastRequest(BaseModel):
    """
    Incoming request payload for forecasting.
    """
    history: List[SensorPoint] = Field(
        ...,
        min_length=48,
        description="Historical sensor observations. Should include enough buffer (e.g. >=72 rows)."
    )


class DailySummaryItem(BaseModel):
    day: int = Field(..., ge=1, description="1-based day index in forecast horizon.")
    max_pm10: float = Field(..., description="Maximum PM10 value in that 24h block.")


class ForecastResponse(BaseModel):
    """
    New frontend-friendly response:
    - daily_summary for cards
    - hourly_predictions for charts
    """
    requested_hours: int = Field(..., description="Forecast horizon requested by client.")
    daily_summary: List[DailySummaryItem] = Field(..., description="Max PM10 for each 24h block.")
    hourly_predictions: List[float] = Field(..., description="Raw hourly PM10 predictions.")