from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.realtime.simulation_models import SimulationEvent

router = APIRouter(prefix="/dev/simulation", tags=["development"])


class SimulationEventBody(BaseModel):
    event_id: str
    scenario_id: str
    sequence: int
    event_type: str
    occurred_at: str
    payload: dict[str, Any]


@router.post("/events")
async def apply_simulation_event(request: Request, body: SimulationEventBody):
    if not request.app.state.settings.enable_simulation_api:
        raise HTTPException(status_code=404)
    try:
        event = SimulationEvent.model_validate(body.model_dump())
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid simulation event") from error
    return await request.app.state.runtime.apply_simulation(event)


@router.post("/reset")
async def reset_simulation(request: Request):
    if not request.app.state.settings.enable_simulation_api:
        raise HTTPException(status_code=404)
    request.app.state.runtime.reset()
    return {"status": "reset"}
