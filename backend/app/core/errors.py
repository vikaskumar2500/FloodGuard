from fastapi import Request
from fastapi.responses import JSONResponse


def problem_response(
    request: Request, status_code: int, code: str, title: str, detail: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        content={
            "type": f"urn:floodguard:problem:{code.lower().replace('_', '-')}",
            "title": title,
            "status": status_code,
            "code": code,
            "detail": detail,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
