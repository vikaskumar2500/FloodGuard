from fastapi import APIRouter, Request, Response

from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


def live_health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
        request_id=request.state.request_id,
    )


@router.get("/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    return live_health(request)


@router.get("", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}})
@router.get(
    "/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}}
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    health = await request.app.state.health_service.readiness(request.state.request_id)
    response.status_code = 200 if health.ready else 503
    response.headers["Cache-Control"] = "no-store"
    return health
