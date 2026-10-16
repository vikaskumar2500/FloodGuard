from fastapi import Request

from .runtime import FloodGuardRuntime


def get_runtime(request: Request) -> FloodGuardRuntime:
    return request.app.state.runtime


def get_route_registry(request: Request):
    return get_runtime(request).route_registry


def get_realtime_publisher(request: Request):
    return get_runtime(request).realtime_publisher


def get_runtime_risk_state(request: Request):
    return get_runtime(request).runtime_risk_state


def get_reroute_coordinator(request: Request):
    return get_runtime(request).reroute_coordinator
