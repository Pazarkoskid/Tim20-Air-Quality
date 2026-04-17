from fastapi import APIRouter, HTTPException, Query, Request

from models import ForecastRequest, ForecastResponse


router = APIRouter(prefix="", tags=["forecast"])


@router.post("/forecast", response_model=ForecastResponse)
def forecast_pm10(
    payload: ForecastRequest,
    request: Request,
    hours: int = Query(default=72, description="Forecast horizon in hours. Must be one of 24, 48, 72."),):
    """
    Forecast PM10 for requested horizon (24/48/72) using preloaded model bundles.
    """
    if hours not in (24, 48, 72):
        raise HTTPException(status_code=422, detail="hours must be one of: 24, 48, 72")

    ml_service = request.app.state.ml_service
    if ml_service is None:
        raise HTTPException(status_code=500, detail="ML service not initialized")

    try:
        result = ml_service.forecast(
            history=[p.model_dump() for p in payload.history],
            hours=hours
        )
        return ForecastResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Artifact error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")