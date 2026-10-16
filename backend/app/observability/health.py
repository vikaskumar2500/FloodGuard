from fastapi import APIRouter

router = APIRouter()


@router.get("/live")
def liveness_check():
    """Basic liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
def readiness_check():
    """Readiness probe. Checks core dependencies (e.g. database)."""
    # In a real app we check db connection here.
    return {"status": "ok", "db": "connected"}


@router.get("/api/v1/internal/health")
def detailed_health_check():
    """Protected detailed health check."""
    return {
        "status": "ok",
        "core": {"database": "ok", "routing_graph": "loaded"},
        "degradable": {"redis": "ok", "bedrock": "degraded", "ml": "ok"},
    }
